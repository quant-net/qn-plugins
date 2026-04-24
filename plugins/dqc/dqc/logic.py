import logging
from quantnet_controller.common.request import RequestManager, RequestType
from quantnet_controller.common.request_translator import RequestTranslator
from quantnet_controller.common.experimentdefinitions import Experiment, AgentSequences, Sequence, get_num_timeslot
from quantnet_controller.common.constants import Constants
from datetime import timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

class DQCLogic:
    def __init__(self, context):
        self.context = context

    @staticmethod
    def extract_qpu_pairs(commands_list):
        """Return unique canonical (src, dst) QPU pairs from cross-QPU commands.

        A cross-QPU command is one whose ``qpus_involved`` list contains two or
        more QPU IDs (e.g. an entanglement-generation operation).  Pairs are
        returned in sorted order so that (A, B) and (B, A) map to the same key.

        :param commands_list: Flat list of command dicts from the DQC request.
        :returns: Deduplicated list of ``(qpu_a, qpu_b)`` string tuples.
        :rtype: list[tuple[str, str]]
        """
        pairs = set()
        for cmd in commands_list:
            qpus = cmd.get('qpus_involved') or []
            if len(qpus) >= 2:
                src, dst = str(qpus[0]), str(qpus[1])
                pairs.add(tuple(sorted([src, dst])))
        return list(pairs)

    def extract_bsm_nodes_from_path(self, path):
        """Return the first available BSMNode ID from a router Path object.

        Iterates over *path.hops* in order and returns a single-element list
        containing the first BSM node whose latest agent state is ``IN_SPEC``.
        If no BSM node is available, returns an empty list.

        :param path: Path object returned by ``router.find_path``.
        :type path: quantnet_controller.common.plugin.Path
        :returns: List with at most one BSMNode ID string.
        :rtype: list[str]
        """
        if path is None or path.hops is None:
            return []
        for hop in path.hops:
            if not (hasattr(hop, 'systemSettings') and hop.systemSettings.type == 'BSMNode'):
                continue
            bsm_id = str(hop.systemSettings.ID)
            state = self.context.rm.get_node_state(bsm_id)
            if state and state.get('value') == 'IN_SPEC':
                logger.debug(f"Selected BSM node {bsm_id} (IN_SPEC)")
                return [bsm_id]
            logger.debug(f"Skipping BSM node {bsm_id} (state={state.get('value') if state else 'unknown'})")
        return []

    def build_dynamic_experiment(self, exp_name, commands_list, node_types=None):
        """Build a dynamic Experiment class from the commands list.

        Each generated sequence block will store its original commands in a 
        `command_list` class attribute.

        :param exp_name: Unique name for the generated experiment class.
        :param commands_list: Flat list of command dicts.
        :param node_types: Optional dict mapping agent/QPU IDs to their node type string.
        :returns: The generated Experiment class.
        """
        if not commands_list:
            return None
        if node_types is None:
            node_types = {}

        # Group commands by agent/qpu
        commands_by_agent = defaultdict(list)
        for cmd in commands_list:
            qpu_id = str(cmd.get('qpu_id'))
            commands_by_agent[qpu_id].append(cmd)

        agent_ids = sorted(list(commands_by_agent.keys()))
        
        class DynamicExperiment(Experiment):
            name = exp_name
            agent_sequences = []

            @classmethod
            def get_allocations(cls, slots_to_allocate, slot_size_sec):
                """Transform flat allocated slots into enriched command blocks."""
                allocations = {}
                # Match agent sequences to allocated slots in order
                for agent_id, agent_seq in zip(agent_ids, cls.agent_sequences):
                    agent_slots = slots_to_allocate[agent_id]
                    slot_ptr = 0
                    blocks = []
                    for seq in agent_seq.sequences:
                        num = get_num_timeslot(seq)
                        block_slots = agent_slots[slot_ptr : slot_ptr + num]
                        if block_slots:
                            blocks.append({
                                "offset": round(block_slots[0] * slot_size_sec, 6),
                                "commands": [
                                    {"slot": s, "message": c}
                                    for s, c in zip(block_slots, getattr(seq, 'command_list', []))
                                ]
                            })
                        slot_ptr += num
                    allocations[agent_id] = blocks
                return allocations

        for agent_id in agent_ids:
            cmds = sorted(commands_by_agent[agent_id], key=lambda x: x.get('timeslot', 0))
            
            _agent_node_type = node_types.get(agent_id, "QNode")

            class DynamicAgentSeq(AgentSequences):
                name = f"Seq_{agent_id}"
                node_type = _agent_node_type
                sequences = []
                
            agent_sequences_list = []
            current_block = []
            prev_qpus_involved = None
            block_index = 0
            
            def create_sequence_from_block(block, b_idx, seq_list):
                first_cmd_raw = block[0].get('command', '')
                first_cmd = str(first_cmd_raw) if first_cmd_raw is not None else ""
                first_op = first_cmd.split(' ')[0] if first_cmd else "Unknown"
                seq_name = f"Block_{b_idx}_{first_op}"
                total_duration = Constants.SLOTSIZE * len(block)
                deps = []
                if len(seq_list) > 0:
                    deps.append(seq_list[-1].name)
                    
                class BlockSequence(Sequence):
                    name = seq_name
                    class_name = seq_name
                    duration = total_duration
                    dependency = deps
                    command_list = [c.get('command') for c in block]

                return BlockSequence

            for cmd in cmds:
                qpus_inv = cmd.get('qpus_involved', [])
                if qpus_inv is None: qpus_inv = []
                current_qpus_involved = set(str(q) for q in qpus_inv) if qpus_inv else set()
                
                is_boundary = False
                if prev_qpus_involved is not None and current_qpus_involved != prev_qpus_involved:
                    is_boundary = True
                
                if is_boundary and current_block:
                    seq_class = create_sequence_from_block(current_block, block_index, agent_sequences_list)
                    agent_sequences_list.append(seq_class)
                    block_index += 1
                    current_block = []
                
                current_block.append(cmd)
                prev_qpus_involved = current_qpus_involved
                
            if current_block:
                seq_class = create_sequence_from_block(current_block, block_index, agent_sequences_list)
                agent_sequences_list.append(seq_class)
            
            DynamicAgentSeq.sequences = agent_sequences_list
            DynamicExperiment.agent_sequences.append(DynamicAgentSeq)

        return DynamicExperiment
