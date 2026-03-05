import logging
from quantnet_controller.common.request import RequestManager, RequestType
from quantnet_controller.common.request_translator import RequestTranslator
from quantnet_controller.common.experimentdefinitions import Experiment, AgentSequences, Sequence
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

    @staticmethod
    def extract_bsm_nodes_from_path(path):
        """Extract BSMNode IDs from a router Path object.

        Iterates over *path.hops* and collects every node whose
        ``systemSettings.type`` equals ``"BSMNode"``.

        :param path: Path object returned by ``router.find_path``.
        :type path: quantnet_controller.common.plugin.Path
        :returns: List of BSMNode ID strings found on the path.
        :rtype: list[str]
        """
        bsm_ids = []
        if path is None or path.hops is None:
            return bsm_ids
        for hop in path.hops:
            if hasattr(hop, 'systemSettings') and hop.systemSettings.type == 'BSMNode':
                bsm_ids.append(str(hop.systemSettings.ID))
        return bsm_ids

    def build_dynamic_experiment(self, exp_name, commands_list, node_types=None):
        """Build a dynamic Experiment class from the commands list.

        :param exp_name: Unique name for the generated experiment class.
        :param commands_list: Flat list of command dicts (may include injected BSM commands).
        :param node_types: Optional dict mapping agent/QPU IDs to their node type string
            (e.g. ``{"BSM-1": "BSMNode", "QPU-A": "QNode"}``).  Defaults to
            ``"QNode"`` for any agent not present in the dict.
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
                total_duration = timedelta(microseconds=1000 * len(block))
                deps = []
                if len(seq_list) > 0:
                    deps.append(seq_list[-1].name)
                    
                class BlockSequence(Sequence):
                    name = seq_name
                    class_name = seq_name
                    duration = total_duration
                    dependency = deps
                
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
