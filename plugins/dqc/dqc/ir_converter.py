"""
ir_converter.py
---------------
Converts labeled per-QPU IR commands into the flat timeslot record format
consumed by DQCLogic.build_dynamic_experiment().

The algorithm is adapted from ControllerProtocol.compute_timeslot_schedule()
in qnpack/qnpack/dqc/protocols/controller.py — a cursor-based scheduler that
advances QPUs in lock-step at sync points (entanglement_gen / ejpp start/end)
and independently for local gates.

Input (from label_and_build_maps):
    labeled_commands : {int_qpu_id: [cmd_dict, ...]}
    process_maps     : {start_qpus, end_qpus, entanglement_gen_labels}
    qpu_id_to_label  : {int_qpu_id: "LBNL-A", ...}

Output (consumed by DQCLogic.build_dynamic_experiment):
    list[dict] with keys:
        timeslot        int     Monotonic timeslot index (0-based)
        qpu_id          str     Topology label, e.g. "LBNL-A"
        command         str     Text representation, e.g. "H server_1[0]"
        command_type    str     "local_gate" | "starting_process_on_demand" |
                                "ending_process" | "idle"
        qpus_involved   list    Topology labels of all QPUs in this sync group
        params          list    Numeric parameters (pass-through)
        qubits          list    Qubit indices (pass-through)
        original_qubits list    Original qubit identifiers (pass-through)
"""

import logging

logger = logging.getLogger(__name__)

# ── Command-type mapping ──────────────────────────────────────────────────────

_OP_TO_COMMAND_TYPE = {
    "entanglement_gen": "starting_process_on_demand",
    "ejpp_start": "starting_process_on_demand",
    "ejpp_start_link": "starting_process_on_demand",
    "ejpp_end": "ending_process",
    "ejpp_end_link": "ending_process",
    "msg_sender": "ending_process",
    "msg_receiver": "ending_process",
    "pre_entanglement": "starting_process_on_demand",
}

_LOCAL_GATE_OPS = frozenset(
    [
        "gate",
        "h",
        "x",
        "y",
        "z",
        "s",
        "t",
        "sdg",
        "tdg",
        "cx",
        "cy",
        "cz",
        "swap",
        "ccx",
        "rx",
        "ry",
        "rz",
        "u1",
        "u2",
        "u3",
        "measure",
        "measure_final",
        "reset",
        "if_gate",  # should have been replaced but kept as fallback
    ]
)


def cmd_to_type(cmd):
    """Map a canonical command dict to a command_type string."""
    op = cmd.get("op", "")
    if op == "gate":
        return "local_gate"
    return _OP_TO_COMMAND_TYPE.get(op, "local_gate")


def cmd_to_text(cmd):
    """Build a human-readable text representation of a command dict.

    Examples:
        gate h  → "H server_1[0]"
        gate cx → "CX server_1[0], server_1[1]"
        entanglement_gen emitter → "ENTG server_1[0]->server_2[0]"
        ejpp_start  → "EJPP_START (sl=0)"
        measure     → "MEASURE server_1[0]"
    """
    op = cmd.get("op", "unknown")
    orig = cmd.get("original_qubits", [])
    sl = cmd.get("start_label") or cmd.get("target_start_label")
    el = cmd.get("end_label")

    if op == "gate":
        gate = cmd.get("gate", "gate").upper()
        args = ", ".join(orig) if orig else ""
        return f"{gate} {args}".strip()

    if op == "entanglement_gen":
        role = cmd.get("role", "")
        label = cmd.get("entanglement_label", "")
        if orig:
            return f"ENTG[{label}] {', '.join(orig)} ({role})"
        return f"ENTG[{label}] ({role})"

    if op == "pre_entanglement":
        desc = f"PRE_ENTG (sl={sl})" if sl is not None else "PRE_ENTG"
        return desc

    if op in ("ejpp_start", "ejpp_start_link", "ejpp_end", "ejpp_end_link"):
        label_str = cmd.get("label", op)
        suffix = f" (sl={sl})" if sl is not None else (f" (el={el})" if el is not None else "")
        return f"{label_str.upper()}{suffix}"

    if op in ("measure", "measure_final"):
        args = ", ".join(orig) if orig else ""
        return f"{op.upper()} {args}".strip()

    if op in ("msg_sender", "msg_receiver"):
        exch_label = cmd.get("label", "")
        return f"{op.upper()} [{exch_label}]"

    # Fallback: op + original qubits
    desc = f"{op.upper()} {', '.join(orig)}" if orig else op.upper()
    if sl is not None:
        desc += f" (sl={sl})"
    elif el is not None:
        desc += f" (el={el})"
    return desc


def _is_sync_cmd(cmd):
    """Return True if this command requires cross-QPU synchronisation."""
    if cmd is None:
        return False
    op = cmd.get("op", "")
    if op == "entanglement_gen" and cmd.get("entanglement_label") is not None:
        return True
    if cmd.get("start_label") is not None:
        return True
    if cmd.get("end_label") is not None:
        return True
    return False


# ── Main converter ────────────────────────────────────────────────────────────


def labeled_ir_to_timeslot_schedule(labeled_commands, process_maps, qpu_id_to_label):
    """Convert labeled per-QPU commands to a flat timeslot schedule.

    The cursor-based algorithm mirrors ControllerProtocol.compute_timeslot_schedule().
    At each iteration one timeslot is produced; the QPUs that advance are those
    participating in the highest-priority sync event, or all non-blocked QPUs
    for local gate steps.

    Priority order (same as controller):
        1. entanglement_gen labels (requires all emitter/peer QPUs at cursor)
        2. start_labels (ejpp_start + ejpp_start_link must both be at cursor)
        3. end_labels   (ejpp_end + ejpp_end_link must both be at cursor)
        4. Local (non-sync) gates — all ready QPUs advance in parallel
        5. Fallback: advance any single blocked QPU

    :param labeled_commands: ``{int_qpu_id: [cmd_dict, ...]}`` from label_and_build_maps
    :param process_maps: ``{start_qpus, end_qpus, entanglement_gen_labels}``
    :param qpu_id_to_label: ``{int_qpu_id: "LBNL-A", ...}``
    :returns: Flat list of timeslot record dicts.
    :rtype: list[dict]
    """
    qpu_ids = sorted(labeled_commands.keys())
    cursors = {qid: 0 for qid in qpu_ids}

    # Pre-compute per-label required QPU sets from process_maps
    start_qpus = process_maps.get("start_qpus", {})  # label -> set(qpu_ids)
    end_qpus = process_maps.get("end_qpus", {})  # label -> set(qpu_ids)
    # entanglement_labels = process_maps.get("entanglement_gen_labels", set())

    schedule = []
    timeslot = 0
    max_iterations = sum(len(cmds) for cmds in labeled_commands.values()) * 2 + 10

    def current_cmd(qid):
        idx = cursors[qid]
        cmds = labeled_commands[qid]
        return cmds[idx] if idx < len(cmds) else None

    def make_record(qid, cmd, ts, qpus_involved_labels):
        label = qpu_id_to_label.get(qid, str(qid))
        return {
            "timeslot": ts,
            "qpu_id": label,
            "command": cmd_to_text(cmd),
            "command_type": cmd_to_type(cmd),
            "qpus_involved": qpus_involved_labels,
            "params": cmd.get("params", []),
            "qubits": cmd.get("qubits", []),
            "original_qubits": cmd.get("original_qubits", []),
        }

    for _ in range(max_iterations):
        # Check if all QPUs have finished
        if all(cursors[qid] >= len(labeled_commands[qid]) for qid in qpu_ids):
            break

        advanced = set()
        records = []
        sync_found = False

        # Collect current label sets at each QPU's cursor
        current_ent_labels = {}  # ent_label -> set(qpu_ids) at cursor
        current_start_labels = {}  # start_label -> set(qpu_ids) at cursor
        current_end_labels = {}  # end_label -> set(qpu_ids) at cursor

        for qid in qpu_ids:
            cmd = current_cmd(qid)
            if cmd is None:
                continue
            op = cmd.get("op", "")
            ent_l = cmd.get("entanglement_label")
            sl = cmd.get("start_label")
            el = cmd.get("end_label")
            if op == "entanglement_gen" and ent_l is not None:
                current_ent_labels.setdefault(ent_l, set()).add(qid)
            if sl is not None:
                current_start_labels.setdefault(sl, set()).add(qid)
            if el is not None:
                current_end_labels.setdefault(el, set()).add(qid)

        # Priority 1: entanglement_gen sync
        for label in sorted(current_ent_labels.keys(), key=str):
            required = start_qpus.get(label, set())
            ready = current_ent_labels.get(label, set())
            if required and required == ready:
                involved_labels = [qpu_id_to_label.get(q, str(q)) for q in sorted(required)]
                for qid in sorted(required):
                    cmd = current_cmd(qid)
                    records.append(make_record(qid, cmd, timeslot, involved_labels))
                    advanced.add(qid)
                sync_found = True
                break

        # Priority 2: start_label sync (ejpp_start + ejpp_start_link)
        if not sync_found:
            for label in sorted(current_start_labels.keys(), key=str):
                required = start_qpus.get(label, set())
                ready = current_start_labels.get(label, set())
                if required and required == ready:
                    involved_labels = [qpu_id_to_label.get(q, str(q)) for q in sorted(required)]
                    for qid in sorted(required):
                        cmd = current_cmd(qid)
                        records.append(make_record(qid, cmd, timeslot, involved_labels))
                        advanced.add(qid)
                    sync_found = True
                    break

        # Priority 3: end_label sync (ejpp_end + ejpp_end_link)
        if not sync_found:
            for label in sorted(current_end_labels.keys(), key=str):
                required = end_qpus.get(label, set())
                ready = current_end_labels.get(label, set())
                if required and required == ready:
                    involved_labels = [qpu_id_to_label.get(q, str(q)) for q in sorted(required)]
                    for qid in sorted(required):
                        cmd = current_cmd(qid)
                        records.append(make_record(qid, cmd, timeslot, involved_labels))
                        advanced.add(qid)
                    sync_found = True
                    break

        # Priority 4: local (non-sync) commands — all ready QPUs advance
        if not sync_found:
            for qid in qpu_ids:
                cmd = current_cmd(qid)
                if cmd is None:
                    continue
                if _is_sync_cmd(cmd):
                    continue  # blocked waiting for peer
                own_label = [qpu_id_to_label.get(qid, str(qid))]
                records.append(make_record(qid, cmd, timeslot, own_label))
                advanced.add(qid)

        # Priority 5: fallback — advance any single blocked QPU (avoids deadlock)
        if not advanced:
            for qid in qpu_ids:
                cmd = current_cmd(qid)
                if cmd is not None:
                    own_label = [qpu_id_to_label.get(qid, str(qid))]
                    records.append(make_record(qid, cmd, timeslot, own_label))
                    advanced.add(qid)
                    logger.warning(
                        f"[ir_converter] Fallback advance on QPU {qid} at " f"timeslot {timeslot}: {cmd_to_text(cmd)}"
                    )
                    break

        if not advanced:
            break  # nothing left to do

        for qid in advanced:
            cursors[qid] += 1

        schedule.extend(records)
        timeslot += 1

    else:
        logger.warning(
            f"[ir_converter] Reached max_iterations={max_iterations} without "
            f"completing the schedule. Remaining cursors: "
            f"{ {qid: (cursors[qid], len(labeled_commands[qid])) for qid in qpu_ids} }"
        )

    logger.debug(f"[ir_converter] Generated {timeslot} timeslots, " f"{len(schedule)} records for {len(qpu_ids)} QPUs")
    return schedule
