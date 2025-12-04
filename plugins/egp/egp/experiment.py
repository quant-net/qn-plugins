from quantnet_controller.common.experimentdefinitions import Sequence, AgentSequences, Experiment
from datetime import timedelta


class QnodeEGP(Sequence):
    name = "experiments/dds_output.py"
    class_name = "DdsOutput"
    duration = timedelta(microseconds=1000)
    dependency = []


class BSMnodeEGP(Sequence):
    name = "experiments/dds_output.py"
    class_name = "DdsOutput"
    duration = timedelta(microseconds=2000)
    dependency = []


class RepeaterEGP(Sequence):
    name = "experiments/dds_output.py"
    class_name = "DdsOutput"
    duration = timedelta(microseconds=3000)
    dependency = []


class QnodeBlackQuantun(Sequence):
    name = "QnodeBlackQuantum.py"
    duration = timedelta(microseconds=4000)
    dependency = []


class BSMnodeBlackQuantum(Sequence):
    name = "BSMnodeBlackQuantum.py"
    duration = timedelta(microseconds=5000)
    dependency = []


class EGPQnodeSequence(AgentSequences):
    name = "Entanglement Generation sequence for Qnode"
    node_type = "QNode"
    sequences = [QnodeEGP]


class EGPBSMnodeSequence(AgentSequences):
    name = "Entanglement Generation sequence for BSMnode"
    node_type = "BSMNode"
    sequences = [BSMnodeEGP]


class RepeaterEGP(AgentSequences):
    name = "Entanglement Generation sequence for Repeater"
    node_type = "RepeaterNode"
    sequences = [RepeaterEGP]


class EntanglementGeneration(Experiment):
    name = "Entanglement Generation"
    agent_sequences = [EGPQnodeSequence, EGPQnodeSequence, EGPBSMnodeSequence]

    def get_sequence(self, agent_index):
        return self.agent_sequences[agent_index]
