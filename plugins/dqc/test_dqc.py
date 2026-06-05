import unittest
import os
import sys
from unittest.mock import MagicMock
from datetime import timedelta

# --- MOCKING MODULES BEFORE IMPORT ---

mock_exp_defs = MagicMock()


class MockExperiment:
    pass


class MockAgentSequences:
    pass


class MockSequence:
    pass


mock_exp_defs.Experiment = MockExperiment
mock_exp_defs.AgentSequences = MockAgentSequences
mock_exp_defs.Sequence = MockSequence


mock_exp_defs.Sequence.duration = timedelta(seconds=0)

sys.modules["quantnet_controller.common.experimentdefinitions"] = mock_exp_defs

mock_request = MagicMock()
mock_request.RequestManager = MagicMock()
mock_request.RequestType = MagicMock()
sys.modules["quantnet_controller.common.request"] = mock_request

mock_translator_mod = MagicMock()
mock_translator_class = MagicMock()
mock_translator_mod.RequestTranslator = mock_translator_class
sys.modules["quantnet_controller.common.request_translator"] = mock_translator_mod

mock_plugin = MagicMock()
mock_plugin.ProtocolPlugin = MagicMock()
mock_plugin.PluginType = MagicMock()
sys.modules["quantnet_controller.common.plugin"] = mock_plugin

mock_mq = MagicMock()
mock_mq.Code = MagicMock()
mock_mq.schema = MagicMock()
sys.modules["quantnet_mq"] = mock_mq
sys.modules["quantnet_mq.schema.models"] = MagicMock()

# Make `from logic import DQCLogic` inside dqc/__init__.py resolve correctly.
# The plugin runtime adds the plugin folder to sys.path; replicate that here.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dqc"))

# Import logic
from dqc.logic import DQCLogic


class TestDQCLogic(unittest.TestCase):
    def setUp(self):
        self.context = MagicMock()
        self.context.config = MagicMock()

    def test_build_dynamic_experiment(self):
        logic = DQCLogic(self.context)

        # Flat array structure with qpus_involved
        commands_list = [
            {"timeslot": 0, "qpu_id": "LBNL-A", "command": "waiting", "qpus_involved": []},
            {
                "timeslot": 1,
                "qpu_id": "LBNL-A",
                "command": "ENTG server_1_link_register[0], server_0_link_register[0]",
                "qpus_involved": ["LBNL-A", "LBNL-B"],
            },
            {
                "timeslot": 2,
                "qpu_id": "LBNL-A",
                "command": "CU1(1) server_0_link_register[1], server_0_link_register[0]",
                "qpus_involved": ["LBNL-A"],
            },
            {"timeslot": 3, "qpu_id": "LBNL-A", "command": "H server_1[0]", "qpus_involved": ["LBNL-A"]},
            {"timeslot": 0, "qpu_id": "LBNL-B", "command": "waiting", "qpus_involved": []},
            {
                "timeslot": 1,
                "qpu_id": "LBNL-B",
                "command": "ENTG server_1_link_register[0], server_0_link_register[0]",
                "qpus_involved": ["LBNL-A", "LBNL-B"],
            },
        ]

        dynamic_experiment = logic.build_dynamic_experiment("TestExp", commands_list)

        self.assertEqual(dynamic_experiment.name, "TestExp")
        agent_ids = ["LBNL-A", "LBNL-B"]

        # Check Agent LBNL-A Sequences
        # Note: build_dynamic_experiment doesn't return agent_ids as a separate list anymore,
        # but they are in DynamicExperiment.agent_sequences named Seq_<agent_id>
        agent_seq_names = [s.name for s in dynamic_experiment.agent_sequences]
        self.assertIn("Seq_LBNL-A", agent_seq_names)
        self.assertIn("Seq_LBNL-B", agent_seq_names)

        agent1_seq = [s for s in dynamic_experiment.agent_sequences if s.name == "Seq_LBNL-A"][0]
        seqs = agent1_seq.sequences

        self.assertEqual(len(seqs), 3)
        self.assertEqual(seqs[0].name, "Block_0_waiting")
        self.assertEqual(seqs[0].duration, timedelta(microseconds=1000 * 1))

        self.assertEqual(seqs[1].name, "Block_1_ENTG")
        self.assertEqual(seqs[1].duration, timedelta(microseconds=1000 * 1))

        self.assertEqual(seqs[2].name, "Block_2_CU1(1)")
        self.assertEqual(seqs[2].duration, timedelta(microseconds=1000 * 2))  # Two commands in this block

        # Check dependencies within LBNL-A
        self.assertEqual(seqs[0].dependency, [])
        self.assertEqual(seqs[1].dependency, ["Block_0_waiting"])
        self.assertEqual(seqs[2].dependency, ["Block_1_ENTG"])

        # Check Agent LBNL-B Sequences
        agent2_seq = [s for s in dynamic_experiment.agent_sequences if s.name == "Seq_LBNL-B"][0]
        seqs2 = agent2_seq.sequences

        self.assertEqual(len(seqs2), 2)
        self.assertEqual(seqs2[0].name, "Block_0_waiting")
        self.assertEqual(seqs2[1].name, "Block_1_ENTG")

    def test_extract_qpu_pairs_basic(self):
        """Cross-QPU commands produce canonical, deduplicated pairs."""
        logic = DQCLogic(self.context)
        commands = [
            {"timeslot": 0, "qpu_id": "LBNL-A", "command": "waiting", "qpus_involved": []},
            {"timeslot": 1, "qpu_id": "LBNL-A", "command": "ENTG ...", "qpus_involved": ["LBNL-A", "LBNL-B"]},
            {"timeslot": 1, "qpu_id": "LBNL-B", "command": "ENTG ...", "qpus_involved": ["LBNL-A", "LBNL-B"]},
            {"timeslot": 2, "qpu_id": "LBNL-A", "command": "H ...", "qpus_involved": ["LBNL-A"]},
        ]
        pairs = logic.extract_qpu_pairs(commands)
        # Duplicate cross-QPU entry should appear only once
        self.assertEqual(len(pairs), 1)
        self.assertIn(("LBNL-A", "LBNL-B"), pairs)

    def test_extract_qpu_pairs_canonical_order(self):
        """Pairs are stored in sorted order regardless of which QPU appears first."""
        logic = DQCLogic(self.context)
        commands = [
            {"timeslot": 0, "qpu_id": "LBNL-B", "command": "ENTG ...", "qpus_involved": ["LBNL-B", "LBNL-A"]},
        ]
        pairs = logic.extract_qpu_pairs(commands)
        self.assertEqual(pairs, [("LBNL-A", "LBNL-B")])

    def test_extract_qpu_pairs_empty(self):
        """Commands with no cross-QPU involvement return an empty list."""
        logic = DQCLogic(self.context)
        commands = [
            {"timeslot": 0, "qpu_id": "LBNL-A", "command": "H ...", "qpus_involved": ["LBNL-A"]},
            {"timeslot": 1, "qpu_id": "LBNL-A", "command": "waiting", "qpus_involved": None},
            {"timeslot": 2, "qpu_id": "LBNL-A", "command": "waiting", "qpus_involved": []},
        ]
        pairs = logic.extract_qpu_pairs(commands)
        self.assertEqual(pairs, [])

    def test_extract_qpu_pairs_multiple(self):
        """Multiple distinct QPU pairs are all returned."""
        logic = DQCLogic(self.context)
        commands = [
            {"timeslot": 0, "qpu_id": "LBNL-A", "command": "ENTG ...", "qpus_involved": ["LBNL-A", "LBNL-B"]},
            {"timeslot": 1, "qpu_id": "LBNL-B", "command": "ENTG ...", "qpus_involved": ["LBNL-B", "LBNL-C"]},
        ]
        pairs = logic.extract_qpu_pairs(commands)
        self.assertEqual(len(pairs), 2)
        self.assertIn(("LBNL-A", "LBNL-B"), pairs)
        self.assertIn(("LBNL-B", "LBNL-C"), pairs)


if __name__ == "__main__":
    unittest.main()
