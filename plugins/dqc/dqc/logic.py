import math
import logging
from datetime import timedelta
from quantnet_controller.common.experimentdefinitions import Experiment, AgentSequences, Sequence, get_num_timeslot
from quantnet_controller.common.constants import Constants
from collections import defaultdict

# Duration of one DQC timeslot from the partitioner (timeslot_schedule.json).
# Multiple DQC timeslots may fit inside a single agent scheduler slot (SLOTSIZE).
DQC_TIMESLOT_MS = 3

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
            qpus = cmd.get("qpus_involved") or []
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
            if not (hasattr(hop, "systemSettings") and hop.systemSettings.type == "BSMNode"):
                continue
            bsm_id = str(hop.systemSettings.ID)
            state = self.context.rm.get_node_state(bsm_id)
            if state and state.get("value") == "IN_SPEC":
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
            qpu_id = str(cmd.get("qpu_id"))
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
                        block_slots = agent_slots[slot_ptr: slot_ptr + num]
                        if block_slots:
                            blocks.append(
                                {
                                    "offset": round(block_slots[0] * slot_size_sec, 6),
                                    "commands": [
                                        {"slot": s, "message": c}
                                        for s, c in zip(block_slots, getattr(seq, "command_list", []))
                                    ],
                                }
                            )
                        slot_ptr += num
                    allocations[agent_id] = blocks
                return allocations

        for agent_id in agent_ids:
            cmds = sorted(commands_by_agent[agent_id], key=lambda x: x.get("timeslot", 0))

            _agent_node_type = node_types.get(agent_id, "QNode")

            class DynamicAgentSeq(AgentSequences):
                name = f"Seq_{agent_id}"
                node_type = _agent_node_type
                sequences = []

            # First pass: collect raw blocks (list of command dicts)
            raw_blocks = []
            current_block = []
            prev_qpus_involved = None
            for cmd in cmds:
                qpus_inv = cmd.get("qpus_involved") or []
                current_qpus_involved = set(str(q) for q in qpus_inv)
                if prev_qpus_involved is not None and current_qpus_involved != prev_qpus_involved:
                    if current_block:
                        raw_blocks.append(current_block)
                    current_block = []
                current_block.append(cmd)
                prev_qpus_involved = current_qpus_involved
            if current_block:
                raw_blocks.append(current_block)

            # Second pass: assign agent-slot durations carrying the fractional remainder
            # forward so leftover time from one block is absorbed by the next block rather
            # than wasting a full agent slot on every block boundary.
            #
            # Strategy: track total DQC time elapsed and total agent slots allocated.
            # For each new block, compute how many new agent slots are needed given what
            # has already been allocated.
            #
            # e.g. SLOTSIZE=100ms, DQC_TIMESLOT=3ms:
            #   block 0: 19 cmds → 57ms total,  ceil(57/100)=1 slot  allocated so far=1
            #   block 1:  1 cmd  → 60ms total,  ceil(60/100)=1 slot  delta=0 → use 1 (min)
            #   block 2:  7 cmds → 81ms total,  ceil(81/100)=1 slot  delta=0 → use 1 (min)
            #   block 3:  1 cmd  → 84ms total,  ceil(84/100)=1 slot  delta=0 → use 1 (min)
            #   block 4:  5 cmds → 99ms total,  ceil(99/100)=1 slot  delta=0 → use 1 (min)
            #   block 5:  2 cmds → 105ms total, ceil(105/100)=2 slots delta=1 → use 1
            #   ...total = 6 agent slots for 6 blocks (vs 6 without packing)
            # When commands pack tightly, multiple blocks share a slot until the ceiling
            # increments — only then is a new slot consumed.
            slotsize_ms = Constants.SLOTSIZE.total_seconds() * 1000
            total_dqc_ms = 0.0
            slots_allocated = 0
            agent_sequences_list = []
            for b_idx, block in enumerate(raw_blocks):
                first_cmd = str(block[0].get("command") or "")
                first_op = first_cmd.split(" ")[0] if first_cmd else "Unknown"
                seq_name = f"Block_{b_idx}_{first_op}"

                total_dqc_ms += len(block) * DQC_TIMESLOT_MS
                new_total_slots = math.ceil(total_dqc_ms / slotsize_ms)
                agent_slots = max(new_total_slots - slots_allocated, 1)
                slots_allocated += agent_slots

                deps = [agent_sequences_list[-1].name] if agent_sequences_list else []
                total_duration = Constants.SLOTSIZE * agent_slots
                cmd_list = [c.get("command") for c in block]

                BlockSequence = type(seq_name, (Sequence,), {
                    "name": seq_name,
                    "class_name": seq_name,
                    "duration": total_duration,
                    "dependency": deps,
                    "command_list": cmd_list,
                })

                agent_sequences_list.append(BlockSequence)

            DynamicAgentSeq.sequences = agent_sequences_list
            DynamicExperiment.agent_sequences.append(DynamicAgentSeq)

        return DynamicExperiment
