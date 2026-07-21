"""
test_dqc_rpc.py
---------------
Integration test client for the DQC plugin.

Two usage modes:

  Tket mode (pre-partitioned commands):
    python test_dqc_rpc.py [partitioned_commands.json]

  Cisco mode (raw QASM circuit content):
    python test_dqc_rpc.py --cisco <circuit.qasm>

If no arguments are provided, a minimal synthetic tket-mode circuit is sent.

The partitioned_commands JSON file must contain a per-QPU command dict::

    {
        "1": [{"op": "gate", "gate": "h", "qubits": [0], ...}, ...],
        "2": [{"op": "ejpp_start_link", ...}, ...]
    }

Keys are string integers (1-based QPU IDs) — matching qnpack's convention.
"""

import os
import sys
import json
import asyncio
from quantnet_mq.rpcclient import RPCClient
from quantnet_mq.schema.models import Schema

# ── Minimal synthetic test circuit (tket mode) ────────────────────────────────

# Field names match tket_frontend.py exactly so qpu.py handlers find what they need.
_SYNTHETIC_TKET_COMMANDS = {
    "1": [
        {
            "op": "gate",
            "gate": "h",
            "qubit": 20,
            "qubits": [20],
            "params": [],
            "original_qubits": ["server_1[0]"],
            "is_remote": False,
            "label": None,
            "start_label": None,
            "end_label": None,
            "clbit": None,
        },
        {
            "op": "ejpp_start",
            "qubit": 20,
            "qubits": [0],
            "params": [],
            "original_qubits": ["server_1_link[0]"],
            "is_remote": True,
            "data_qubit": 20,
            "l_local": 0,
            "link_qpu_id": 2,
            "link_qubit_idx": 0,
            "data_qpu_id": 1,
            "peer_qpu_id": 2,
            "label": None,
            "start_label": None,
            "end_label": None,
            "clbit": None,
        },
        {
            "op": "ejpp_end",
            "qubits": [20],
            "params": [],
            "original_qubits": ["server_1[0]"],
            "is_remote": True,
            "comm_qubit": 0,
            "data_qubit": 20,
            "l_local": 0,
            "link_qpu_id": 2,
            "link_qubit_idx": 0,
            "data_qpu_id": 1,
            "peer_qpu_id": 2,
            "label": None,
            "start_label": None,
            "end_label": None,
            "clbit": None,
        },
    ],
    "2": [
        {
            "op": "ejpp_start_link",
            "qubit": 0,
            "qubits": [0],
            "params": [],
            "original_qubits": ["server_2_link[0]"],
            "is_remote": True,
            "link_qubit_idx": 0,
            "l_local": 0,
            "data_qpu_id": 1,
            "peer_qpu_id": 1,
            "label": None,
            "start_label": None,
            "end_label": None,
            "clbit": None,
        },
        {
            "op": "ejpp_end_link",
            "qubit": 0,
            "qubits": [0],
            "params": [],
            "original_qubits": ["server_2_link[0]"],
            "is_remote": True,
            "link_qubit_idx": 0,
            "data_qpu_id": 1,
            "peer_qpu_id": 1,
            "label": None,
            "start_label": None,
            "end_label": None,
            "clbit": None,
        },
        {
            "op": "gate",
            "gate": "x",
            "qubit": 20,
            "qubits": [20],
            "params": [],
            "original_qubits": ["server_2[0]"],
            "is_remote": False,
            "label": None,
            "start_label": None,
            "end_label": None,
            "clbit": None,
        },
    ],
}


class DQCTestClient:
    def __init__(self, partitioned_commands=None, circuit_mode="tket", circuit_content=None):
        self._partitioned_commands = partitioned_commands
        self._circuit_mode = circuit_mode
        self._circuit_content = circuit_content

    async def do_dqc(self):
        if self._circuit_content is not None:
            msg = {
                "circuit_mode": self._circuit_mode,
                "circuit_content": self._circuit_content,
            }
            print(
                f"Sending DQC request: mode={self._circuit_mode}, circuit_content ({len(self._circuit_content)} chars)"
            )
        else:
            msg = {
                "circuit_mode": self._circuit_mode,
                "partitioned_commands": self._partitioned_commands,
            }
            total_cmds = sum(len(v) for v in self._partitioned_commands.values())
            print(
                f"Sending DQC request: mode={self._circuit_mode}, "
                f"{len(self._partitioned_commands)} QPU(s), {total_cmds} command(s) total"
            )
        return json.loads(await self._client.call("dqcRequest", msg, timeout=120.0))

    async def main(self):
        schema_path = os.path.join(os.path.dirname(__file__), "../schema/dqc.yaml")
        Schema.load_schema(schema_path, ns="dqc")

        self._client = RPCClient("dqc-client", host=os.getenv("HOST", "localhost"))
        self._client.set_handler("dqcRequest", None, "quantnet_mq.schema.models.dqc.dqcRequest")

        await self._client.start()

        try:
            ret = await self.do_dqc()
            print("Response received:")
            print(json.dumps(ret, indent=2))
        except Exception as e:
            print(f"Error during DQC call: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cisco":
        if len(sys.argv) < 3:
            print("Error: --cisco requires a circuit file path")
            sys.exit(1)
        qasm_file = sys.argv[2]
        if not os.path.exists(qasm_file):
            print(f"Error: file not found: {qasm_file}")
            sys.exit(1)
        with open(qasm_file) as f:
            circuit_content = f.read()
        client = DQCTestClient(circuit_mode="cisco", circuit_content=circuit_content)
    elif len(sys.argv) > 1:
        cmd_file = sys.argv[1]
        if not os.path.exists(cmd_file):
            print(f"Error: file not found: {cmd_file}")
            sys.exit(1)
        with open(cmd_file) as f:
            partitioned_commands = json.load(f)
        print(f"Loaded partitioned commands from {cmd_file}")
        client = DQCTestClient(partitioned_commands=partitioned_commands, circuit_mode="tket")
    else:
        client = DQCTestClient(partitioned_commands=_SYNTHETIC_TKET_COMMANDS, circuit_mode="tket")

    asyncio.run(client.main())
