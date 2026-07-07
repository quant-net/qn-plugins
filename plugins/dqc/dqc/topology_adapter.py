"""
topology_adapter.py
-------------------
Converts live controller topology into the data structures expected by
qnpack frontends and the DQC plugin scheduling pipeline.

The controller's ResourceManager.get_topology(full=True) returns a dict::

    {
        "num_nodes":    int,
        "num_qubits":   int,
        "num_channels": int,
        "nodes": [
            {
                "id": str,
                "systemSettings": {"ID": str, "type": "QNode"|"BSMNode", ...},
                "qubitSettings":  {"qubits": [...], ...},
                "channels":       [...],
                ...
            },
            ...
        ],
        "edges": [...],
    }

qnpack frontends expect qpu_info as::

    {1: {"num_qubits": 40}, 2: {"num_qubits": 40}, ...}

where the keys are 1-based integer QPU IDs.
"""

import logging

logger = logging.getLogger(__name__)


def get_qpu_info_from_topology(context):
    """Query live topology and build frontend-compatible data structures.

    Separates QNode and BSMNode entries. QNodes receive 1-based integer IDs
    (matching qnpack's convention); BSMNodes are returned as-is for use by
    route discovery and BSM command injection.

    :param context: Plugin context — must have ``context.rm`` (ResourceManager).
    :returns: Four-tuple ``(qpu_info, qpu_id_to_label, label_to_qpu_id, bsm_nodes)``:

        - **qpu_info** ``{int: {"num_qubits": int, ...}}`` — 1-based QPU ID →
          qubit count, ready to pass to ``frontend.parse()``.
        - **qpu_id_to_label** ``{int: str}`` — 1-based QPU ID → topology label
          (e.g. ``{1: "LBNL-A", 2: "LBNL-B"}``).
        - **label_to_qpu_id** ``{str: int}`` — reverse mapping.
        - **bsm_nodes** ``list[dict]`` — BSMNode dicts from topology, each
          containing at least ``id`` and ``systemSettings``.

    :raises RuntimeError: If the topology cannot be fetched or contains no
        QNode entries.
    """
    topo = context.rm.get_topology(full=True)
    # qnpack's create_nodes_from_topology expects a list (topology_data[0])
    # matching the on-disk format [{"nodes": [...], "edges": [...], ...}].
    # The live RPC returns a bare dict, so wrap it.
    raw_topology = [dict(topo)]
    nodes = topo.get("nodes", [])

    qnodes = []
    bsm_nodes = []

    for node in nodes:
        sys_settings = node.get("systemSettings", {})
        node_type = sys_settings.get("type", "")
        node_id = str(sys_settings.get("ID", node.get("id", "")))

        if node_type == "QNode":
            qubit_settings = node.get("qubitSettings", {})
            qubits = qubit_settings.get("qubits", [])
            num_qubits = len(qubits)
            qnodes.append({"id": node_id, "num_qubits": num_qubits, "_raw": node})
        elif node_type == "BSMNode":
            bsm_entry = dict(node)
            bsm_entry["id"] = node_id
            bsm_nodes.append(bsm_entry)

    if not qnodes:
        raise RuntimeError(
            "get_qpu_info_from_topology: no QNode entries found in live topology. "
            "Ensure all QPU agents have registered with the controller."
        )

    # Sort by node ID for deterministic 1-based assignment
    qnodes.sort(key=lambda n: n["id"])

    qpu_info = {}
    qpu_id_to_label = {}
    label_to_qpu_id = {}

    for idx, node in enumerate(qnodes, start=1):
        label = node["id"]
        num_q = node["num_qubits"]
        qpu_info[idx] = {"num_qubits": num_q}
        qpu_id_to_label[idx] = label
        label_to_qpu_id[label] = idx

    logger.debug(
        f"[topology_adapter] {len(qnodes)} QNode(s): {qpu_id_to_label}, "
        f"{len(bsm_nodes)} BSMNode(s): {[n['id'] for n in bsm_nodes]}"
    )

    return qpu_info, qpu_id_to_label, label_to_qpu_id, bsm_nodes, raw_topology
