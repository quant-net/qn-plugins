from quantnet_controller.common.experimentdefinitions import Sequence, AgentSequences, Experiment
from datetime import timedelta


class QnodeLBNLSPG(Sequence):
    name = "experiments/single_photon_generation.py"
    class_name = "SinglePhotonGeneration"
    duration = timedelta(microseconds=10000)
    dependency = []


class QnodeUCBSPG(Sequence):
    name = "experiments/single_photon_generation.py"
    class_name = "SinglePhotonGeneration"
    duration = timedelta(microseconds=10000)
    dependency = []


class SPGQnodeLBNLSequence(AgentSequences):
    name = "Single Photon Generation for Qnode@LBNL"
    node_type = "QNode"
    sequences = [QnodeLBNLSPG]


class SPGQnodeUCBSequence(AgentSequences):
    name = "Single Photon Generation for Qnode@UCB"
    node_type = "QNode"
    sequences = [QnodeUCBSPG]


# class SinglePhotonGenerationLBNL(Experiment):
#     name = "Single Photon Generation @ LBNL"
#     agent_sequences = [SPGQnodeLBNLSequence]

#     def get_sequence(self, agent_index):
#         return self.agent_sequences[agent_index]


# class SinglePhotonGenerationUCB(Experiment):
#     name = "Single Photon Generation @ UCB"
#     agent_sequences = [SPGQnodeUCBSequence]

#     def get_sequence(self, agent_index):
#         return self.agent_sequences[agent_index]


class SinglePhotonGeneration(Experiment):
    name = "Single Photon Generation"
    agent_sequences = [SPGQnodeLBNLSequence, SPGQnodeUCBSequence]

    def get_sequence(self, agent_index):
        return self.agent_sequences[agent_index]
