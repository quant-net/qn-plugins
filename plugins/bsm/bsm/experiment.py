from quantnet_controller.common.experimentdefinitions import Sequence, AgentSequences, Experiment
from datetime import timedelta


class QnodeLBNLSPG(Sequence):
    name = "BSM"
    class_name = "BSM"
    duration = timedelta(microseconds=10000)
    dependency = []


class SPGQnodeLBNLSequence(AgentSequences):
    name = "BSM for Qnode@LBNL"
    node_type = "BSMNode"
    sequences = [QnodeLBNLSPG]


class SinglePhotonGenerationLBNL(Experiment):
    name = "BSM"
    agent_sequences = [SPGQnodeLBNLSequence]

    def get_sequence(self, agent_index):
        return self.agent_sequences[agent_index]
