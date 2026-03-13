from quantnet_controller.common.plugin import ProtocolPlugin, PluginType
from quantnet_controller.common.request import RequestManager, RequestType, RequestParameter
from quantnet_controller.common.constants import Constants
from quantnet_mq import Code
from quantnet_mq.schema.models import dqc, Status as responseStatus
from logic import DQCLogic

import logging
logger = logging.getLogger(__name__)


class DQC(ProtocolPlugin):
    def __init__(self, context):
        super().__init__("dqc", PluginType.PROTOCOL, context)
        self._server_commands = [
            ("dqcRequest", self.handle_dqc_request, "quantnet_mq.schema.models.dqc.dqcRequest"),
        ]
        self.ctx = context

        # Initialize logic handler
        self.logic = DQCLogic(context)

        # Initialize RequestManager
        self.request_manager = RequestManager(
            context, plugin_schema=dqc.dqcRequest, request_type=RequestType.EXPERIMENT
        )

    def initialize(self):
        pass

    def destroy(self):
        pass

    def reset(self):
        pass

    async def handle_dqc_request(self, request):
        """Handle incoming DQC request from partitioner."""
        # Deserialize request
        dqc_req = dqc.dqcRequest(**request)
        logger.info(f"Received DQC request: {dqc_req.serialize()}")

        try:
            # 1. Process commands and agent IDs
            # Convert to a plain list of dicts immediately – the raw value is a schema
            # proxy type that doesn't support list concatenation.
            commands = [dict(c) for c in request.get('payload', {}).get('commands', [])]
            agent_ids = sorted(list(set(str(c.get('qpu_id')) for c in commands)))

            # 1b. Find network routes between all cross-QPU pairs (mirrors EGP pattern).
            #     Cross-QPU commands are identified by having >= 2 entries in qpus_involved.
            qpu_pairs = self.logic.extract_qpu_pairs(commands)
            routes = {}
            # Map route_key -> Path object so we can later inspect hops for BSM nodes.
            _path_objects = {}
            if qpu_pairs and hasattr(self.ctx, 'router') and self.ctx.router:
                for (src, dst) in qpu_pairs:
                    route_key = f"{src}->{dst}"
                    try:
                        p = await self.ctx.router.find_path(src, dst)
                        routes[route_key] = p.to_node_ids()
                        _path_objects[route_key] = p
                        logger.info(f"Route found {route_key}: {routes[route_key]}")
                    except Exception as e:
                        logger.warning(f"Could not find route {route_key}: {e}")
                        routes[route_key] = None
                        _path_objects[route_key] = None
            else:
                logger.debug(
                    "No router plugin available or no cross-QPU pairs; skipping route discovery"
                )

            # 1c. Extract BSM nodes from each route and build synthetic BSM commands
            #     so they are included in the experiment and get scheduled.
            node_types = {}  # agent_id -> node type string
            bsm_commands = []  # synthetic commands injected for BSM agents
            _seen_bsm_ids = set()

            for route_key, path_obj in _path_objects.items():
                bsm_ids = self.logic.extract_bsm_nodes_from_path(path_obj)
                if not bsm_ids:
                    continue

                # Determine which cross-QPU commands belong to this route pair.
                src_qpu, dst_qpu = route_key.split("->") if "->" in route_key else (None, None)
                pair_cmds = [
                    c for c in commands
                    if len(c.get('qpus_involved') or []) >= 2
                    and src_qpu in [str(q) for q in c.get('qpus_involved', [])]
                    and dst_qpu in [str(q) for q in c.get('qpus_involved', [])]
                ]

                for bsm_id in bsm_ids:
                    node_types[bsm_id] = 'BSMNode'
                    if bsm_id in _seen_bsm_ids:
                        continue
                    _seen_bsm_ids.add(bsm_id)
                    # Create a synthetic command for each cross-QPU command slot
                    for cmd in pair_cmds:
                        bsm_cmd = dict(cmd)  # shallow copy
                        bsm_cmd['qpu_id'] = bsm_id
                        bsm_cmd['node_type'] = 'BSMNode'
                        bsm_commands.append(bsm_cmd)
                    logger.info(f"Injected {len(pair_cmds)} BSM command(s) for node {bsm_id} on route {route_key}")

            # Merge BSM commands into the full command list and refresh agent_ids.
            if bsm_commands:
                commands = commands + bsm_commands

            # Rebuild agent_ids to include BSM nodes.
            all_agent_ids = sorted(list(set(str(c.get('qpu_id')) for c in commands)))
            agent_ids = all_agent_ids

            # Safely retrieve the rid from either the dqc_req payload if available, or the raw
            # request dictionary.  Use a generated UUID as fallback instead of 'unknown'.
            rid = getattr(dqc_req.payload, 'rid', None) or request.get('id')
            if not rid or rid == 'unknown':
                from quantnet_controller.common.utils import generate_uuid
                rid = generate_uuid()

            # 2. Build dynamic experiment structure
            exp_name = f"DQC_{rid}"
            DynamicExp = self.logic.build_dynamic_experiment(exp_name, commands, node_types=node_types)
            if not DynamicExp:
                raise Exception("No commands to process")

            # 3. Register dynamic experiment with translator
            self.request_manager.translator.exp_defs.append(DynamicExp)

            try:
                start_time, slots = await self.request_manager.translator.get_slots_to_allocate(
                    agent_ids, DynamicExp
                )

                # 4. Enrich allocations using the experiment's own self-description
                allocations = DynamicExp.get_allocations(slots, Constants.SLOTSIZE.total_seconds())

                # 5. Create and schedule request
                parameters = RequestParameter(exp_name=exp_name, path=agent_ids)
                req_obj = self.request_manager.new_request(
                    payload=dqc_req, parameters=parameters, rid=rid
                )

                # Blocking schedule (executes the experiment via translator)
                await self.request_manager.schedule(req_obj, blocking=True)

                return dqc.dqcResponse(
                    status=responseStatus(
                        code=Code.OK.value, value=Code.OK.name, message="DQC execution completed"
                    ),
                    rid=rid,
                    data={"startTime": start_time, "allocations": allocations, "routes": routes},
                )
            finally:
                # cleanup
                if DynamicExp in self.request_manager.translator.exp_defs:
                    self.request_manager.translator.exp_defs.remove(DynamicExp)

        except Exception as e:
            logger.error(f"DQC processing failed: {e}")
            return dqc.dqcResponse(
                status=responseStatus(
                    code=Code.FAILED.value, value=Code.FAILED.name, message=f"{e}"
                ),
                rid=dqc_req.payload.rid if hasattr(dqc_req.payload, 'rid') else "unknown"
            )
