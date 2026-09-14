"""Superdense coding on hardware: 2-qubit baseline, then a whole token hash.

    venv/bin/python experiments/ibm/exp_superdense.py             # dry run
    venv/bin/python experiments/ibm/exp_superdense.py --submit    # ibm_fez

Stages
  protocol  the four 2-bit messages over one Bell pair - the protocol's own
            error floor on this device.
  token     the 8-bit token hash this project actually issues, sent over four
            Bell pairs in one circuit (8 qubits carrying 8 bits with 4 qubits
            of channel traffic).
  decay     the same transmission with an idle storage window between encoding
            and decoding, sweeping the delay to find how long the payload
            survives in the entangled register.

Encoding convention is taken from quantum_circuits/superdense_simulator.py:
distribute h(sender), cx(sender, receiver); encode X if the odd bit, then Z if
the even bit; decode cx(sender, receiver), h(sender); sender measures into the
even classical bit, receiver into the odd one.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister  # noqa: E402

from experiments.ibm.common import (  # noqa: E402
    assert_budget,
    circuit_metrics,
    estimate_qpu_seconds,
    hamming,
    hellinger_fidelity,
    mean_std,
    open_run,
    run_ideal,
    run_sampler,
    shannon_entropy,
    transpile_isa,
)

EXPERIMENT = "superdense"
TOKEN_PAYLOAD = "serial=QT-0001|geo=u2vh|exp=1789000000"
DECAY_DELAYS_US = (0, 25, 50, 100, 200, 400)


# ----------------------------------------------------------------- device layout
def best_disjoint_pairs(backend, n_pairs: int) -> list[dict]:
    """Lowest-error, mutually disjoint coupled qubit pairs, for the record.

    The transpiler picks the actual layout (VF2 finds an exact embedding for a
    graph of disjoint edges); these are reported so the artifact documents what
    the device could offer.
    """
    target = backend.target
    gate = next(g for g in ("cz", "ecr", "cx") if g in target.operation_names)
    scored = []
    for qargs, inst in target[gate].items():
        if not qargs or len(qargs) != 2 or inst is None or inst.error is None:
            continue
        scored.append((inst.error, tuple(qargs)))
    scored.sort()
    chosen, used = [], set()
    for error, (a, b) in scored:
        if a in used or b in used:
            continue
        chosen.append({"pair": [a, b], "gate": gate, "error": error})
        used.update((a, b))
        if len(chosen) == n_pairs:
            break
    return chosen


def isa_layout(isa_circuit) -> list[int] | None:
    layout = getattr(isa_circuit, "layout", None)
    if layout is None:
        return None
    try:
        return list(layout.final_index_layout())
    except Exception:
        return None


# --------------------------------------------------------------------- circuits
def superdense_circuit(bits: str, delay_us: int = 0, name: str = "sdc") -> QuantumCircuit:
    """Send `bits` over len(bits)/2 Bell pairs; optional idle storage window."""
    if len(bits) % 2:
        raise ValueError("superdense coding carries two bits per pair")
    n_pairs = len(bits) // 2
    qr = QuantumRegister(2 * n_pairs, "q")
    cr = ClassicalRegister(2 * n_pairs, "c")
    qc = QuantumCircuit(qr, cr, name=name)

    for i in range(n_pairs):
        sender, receiver = qr[2 * i], qr[2 * i + 1]
        qc.h(sender)
        qc.cx(sender, receiver)
        if bits[2 * i + 1] == "1":
            qc.x(sender)
        if bits[2 * i] == "1":
            qc.z(sender)

    if delay_us:
        qc.barrier()
        qc.delay(delay_us, qr, unit="us")
        qc.barrier()

    for i in range(n_pairs):
        sender, receiver = qr[2 * i], qr[2 * i + 1]
        qc.cx(sender, receiver)
        qc.h(sender)
        qc.measure(sender, cr[2 * i])
        qc.measure(receiver, cr[2 * i + 1])
    return qc


def decoded_bits(bitstring: str, nbits: int) -> str:
    """Classical register is MSB-first; return classical bits 0..nbits-1."""
    return bitstring.replace(" ", "")[::-1][:nbits]


# ---------------------------------------------------------------------- metrics
def transmission_metrics(record: dict, sent: str) -> dict:
    nbits = len(sent)
    per_shot = [decoded_bits(s, nbits) for s in record["bitstrings"]]
    n = len(per_shot)
    exact = sum(1 for s in per_shot if s == sent)
    distances = [hamming(sent, s) for s in per_shot]
    per_bit_errors = [0] * nbits
    for s in per_shot:
        for i in range(nbits):
            if s[i] != sent[i]:
                per_bit_errors[i] += 1
    hist: dict[str, int] = {}
    for d in distances:
        hist[str(d)] = hist.get(str(d), 0) + 1
    decoded_counts: dict[str, int] = {}
    for s in per_shot:
        decoded_counts[s] = decoded_counts.get(s, 0) + 1
    return {
        "sent_bits": sent,
        "shots": n,
        "exact_match_rate": exact / n,
        "mean_bit_error_rate": sum(distances) / (n * nbits),
        "mean_hamming_bits": sum(distances) / n,
        "hamming_histogram": hist,
        "per_bit_error_rate": [e / n for e in per_bit_errors],
        "worst_bit": int(max(range(nbits), key=lambda i: per_bit_errors[i])),
        "decoded_entropy_bits": shannon_entropy(decoded_counts),
        "distinct_decoded": len(decoded_counts),
    }


def fit_storage_lifetime(delays_us, bers) -> dict:
    """BER(t) = 0.5 * (1 - exp(-t/tau)); tau is the payload lifetime."""
    import numpy as np
    from scipy.optimize import curve_fit

    def model(t, tau):
        return 0.5 * (1.0 - np.exp(-t / tau))

    t = np.asarray(delays_us, dtype=float)
    y = np.asarray(bers, dtype=float)
    if y.max() <= 1e-9:
        return {"tau_us": None, "reason": "no decay observed (noiseless reference)"}
    try:
        popt, pcov = curve_fit(model, t, y, p0=[100.0], bounds=(1e-3, 1e6), maxfev=20000)
        residual = y - model(t, *popt)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - float((residual ** 2).sum()) / ss_tot if ss_tot > 0 else None
        return {"tau_us": float(popt[0]),
                "tau_stderr_us": float(math.sqrt(abs(pcov[0][0]))),
                "r_squared": r2}
    except Exception as exc:  # pragma: no cover
        return {"tau_us": None, "reason": f"fit failed: {exc}"}


def crossing(delays_us, values, threshold: float, rising: bool) -> float | None:
    """Linear interpolation of the first threshold crossing."""
    for i in range(1, len(values)):
        a, b = values[i - 1], values[i]
        if (rising and a < threshold <= b) or (not rising and a >= threshold > b):
            span = b - a
            if span == 0:
                return float(delays_us[i])
            frac = (threshold - a) / span
            return float(delays_us[i - 1] + frac * (delays_us[i] - delays_us[i - 1]))
    return None


# ------------------------------------------------------------------------ stages
def token_hash_bits() -> str:
    from quantum_circuits.grover_hash import GroverHash
    hasher = GroverHash(hash_length=8, grover_iterations=1)
    return hasher.compute_hash(TOKEN_PAYLOAD)


def stage_protocol(ctx, args) -> float:
    messages = ["00", "01", "10", "11"]
    circuits = [superdense_circuit(m, name=f"sdc_msg_{m}") for m in messages]
    isa, isa_metrics = transpile_isa(circuits, ctx.backend)
    estimate = estimate_qpu_seconds(isa, args.shots, ctx.backend)
    print(f"\n=== protocol: 4 messages x {args.shots} shots")
    print(f"  isa depth={[m['depth'] for m in isa_metrics]} "
          f"layout={[isa_layout(c) for c in isa]}")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    ideal = run_ideal(circuits, args.shots)

    def analyse(records):
        rows, accuracies = [], []
        confusion = {m: {n: 0 for n in messages} for m in messages}
        for msg, rec in zip(messages, records):
            counts = {decoded_bits(k, 2): v for k, v in rec["counts"].items()}
            total = sum(counts.values())
            for decoded, v in counts.items():
                confusion[msg][decoded] = confusion[msg].get(decoded, 0) + v
            rows.append({
                "message": msg,
                "accuracy": counts.get(msg, 0) / total,
                "distribution": {k: v / total for k, v in counts.items()},
                "counts": counts,
            })
            accuracies.append(counts.get(msg, 0) / total)
        mean, std = mean_std(accuracies)
        bit_errors = 0
        for msg, rec in zip(messages, records):
            for k, v in rec["counts"].items():
                bit_errors += hamming(msg, decoded_bits(k, 2)) * v
        total_bits = sum(sum(r["counts"].values()) for r in rows) * 2
        return {
            "per_message": rows,
            "mean_accuracy": mean,
            "std_accuracy": std,
            "per_bit_error_rate": bit_errors / total_bits,
            "confusion_counts": confusion,
        }

    ideal_analysis = analyse(ideal)
    for row in ideal_analysis["per_message"]:
        assert row["accuracy"] == 1.0, f"ideal message {row['message']} decoded wrongly"
    print(f"  ideal: mean accuracy {ideal_analysis['mean_accuracy']:.3f}")

    payload = {
        "run_id": ctx.run_id, "backend": ctx.backend_name, "stage": "protocol",
        "messages": messages, "shots": args.shots,
        "device_best_pairs": best_disjoint_pairs(ctx.backend, 1),
        "isa_metrics": isa_metrics, "isa_layouts": [isa_layout(c) for c in isa],
        "logical_metrics": [circuit_metrics(c) for c in circuits],
        "estimate": estimate,
    }
    ctx.save(EXPERIMENT, "protocol_2qubit_ideal",
             {**payload, "source": "AerSimulator (noiseless)", "analysis": ideal_analysis,
              "records": ideal})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, args.shots, tag="sdc_protocol")
        analysis = analyse(records)
        for row, ideal_row in zip(analysis["per_message"], ideal_analysis["per_message"]):
            row["hellinger_fidelity_vs_ideal"] = hellinger_fidelity(
                row["counts"], ideal_row["counts"])
        print(f"  hardware: mean accuracy {analysis['mean_accuracy']:.3f} "
              f"+/-{analysis['std_accuracy']:.3f} "
              f"per-bit error {analysis['per_bit_error_rate']:.4f}")
        ctx.save(EXPERIMENT, "protocol_2qubit",
                 {**payload, "source": f"QPU {ctx.backend_name}", "analysis": analysis,
                  "records": records})
    return estimate["estimated_qpu_seconds"]


def stage_token(ctx, args, token_bits: str) -> float:
    circuit = superdense_circuit(token_bits, name="sdc_token")
    isa, isa_metrics = transpile_isa([circuit], ctx.backend)
    estimate = estimate_qpu_seconds(isa, args.shots, ctx.backend)
    print(f"\n=== token: hash {token_bits} over {len(token_bits) // 2} Bell pairs")
    print(f"  isa depth={isa_metrics[0]['depth']} layout={isa_layout(isa[0])}")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    ideal = run_ideal([circuit], args.shots)
    ideal_metrics = transmission_metrics(ideal[0], token_bits)
    assert ideal_metrics["exact_match_rate"] == 1.0, "noiseless transmission must be exact"
    print(f"  ideal: exact match {ideal_metrics['exact_match_rate']:.3f}")

    payload = {
        "run_id": ctx.run_id, "backend": ctx.backend_name, "stage": "token",
        "token_payload": TOKEN_PAYLOAD, "token_bits": token_bits,
        "n_pairs": len(token_bits) // 2, "shots": args.shots,
        "device_best_pairs": best_disjoint_pairs(ctx.backend, len(token_bits) // 2),
        "isa_metrics": isa_metrics, "isa_layouts": [isa_layout(isa[0])],
        "logical_metrics": [circuit_metrics(circuit)], "estimate": estimate,
    }
    ctx.save(EXPERIMENT, "token_transmission_ideal",
             {**payload, "source": "AerSimulator (noiseless)",
              "analysis": ideal_metrics, "records": ideal})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, args.shots, tag="sdc_token")
        metrics = transmission_metrics(records[0], token_bits)
        metrics["hellinger_fidelity_vs_ideal"] = hellinger_fidelity(
            records[0]["counts"], ideal[0]["counts"])
        print(f"  hardware: exact match {metrics['exact_match_rate']:.3f} "
              f"BER {metrics['mean_bit_error_rate']:.4f} "
              f"worst bit {metrics['worst_bit']}")
        ctx.save(EXPERIMENT, "token_transmission",
                 {**payload, "source": f"QPU {ctx.backend_name}",
                  "analysis": metrics, "records": records})
    return estimate["estimated_qpu_seconds"]


def stage_decay(ctx, args, token_bits: str) -> float:
    delays = list(DECAY_DELAYS_US)
    circuits = [superdense_circuit(token_bits, delay_us=d, name=f"sdc_decay_{d}us")
                for d in delays]
    isa, isa_metrics = transpile_isa(circuits, ctx.backend)
    shots = args.decay_shots
    estimate = estimate_qpu_seconds(isa, shots, ctx.backend)
    print(f"\n=== decay: delays {delays} us x {shots} shots")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    ideal = run_ideal(circuits, shots)

    def analyse(records):
        rows = []
        for d, rec in zip(delays, records):
            m = transmission_metrics(rec, token_bits)
            m["delay_us"] = d
            rows.append(m)
        bers = [r["mean_bit_error_rate"] for r in rows]
        exact = [r["exact_match_rate"] for r in rows]
        usable = [d for d, e in zip(delays, exact) if e >= 0.5]
        return {
            "per_delay": rows,
            "delays_us": delays,
            "ber": bers,
            "exact_match_rate": exact,
            "fit": fit_storage_lifetime(delays, bers),
            "max_delay_with_half_exact_match_us": max(usable) if usable else None,
            "delay_at_ber_0p25_us": crossing(delays, bers, 0.25, rising=True),
        }

    ideal_analysis = analyse(ideal)
    for row in ideal_analysis["per_delay"]:
        assert row["exact_match_rate"] == 1.0, \
            f"noiseless run lost data at {row['delay_us']} us"
    print(f"  ideal: exact match at every delay = 1.000")

    payload = {
        "run_id": ctx.run_id, "backend": ctx.backend_name, "stage": "decay",
        "token_bits": token_bits, "delays_us": delays, "shots": shots,
        "isa_metrics": isa_metrics, "estimate": estimate,
        "logical_metrics": [circuit_metrics(c) for c in circuits],
    }
    ctx.save(EXPERIMENT, "token_decay_ideal",
             {**payload, "source": "AerSimulator (noiseless)",
              "analysis": ideal_analysis, "records": ideal})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, shots, tag="sdc_decay")
        analysis = analyse(records)
        print(f"  hardware: BER {[round(b, 4) for b in analysis['ber']]}")
        print(f"  hardware: exact {[round(e, 3) for e in analysis['exact_match_rate']]}")
        print(f"  hardware: tau={analysis['fit'].get('tau_us')} us, "
              f"half-exact up to {analysis['max_delay_with_half_exact_match_us']} us")
        ctx.save(EXPERIMENT, "token_decay",
                 {**payload, "source": f"QPU {ctx.backend_name}",
                  "analysis": analysis, "records": records})
    return estimate["estimated_qpu_seconds"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--decay-shots", type=int, default=1024)
    parser.add_argument("--stage", default="all",
                        choices=["protocol", "token", "decay", "all"])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--reserve", type=float, default=60.0)
    args = parser.parse_args(argv)

    ctx = open_run(run_id=args.run_id)
    token_bits = token_hash_bits()
    print(f"token payload {TOKEN_PAYLOAD!r} -> GroverHash(8) = {token_bits}")

    total = 0.0
    if args.stage in ("protocol", "all"):
        total += stage_protocol(ctx, args)
    if args.stage in ("token", "all"):
        total += stage_token(ctx, args, token_bits)
    if args.stage in ("decay", "all"):
        total += stage_decay(ctx, args, token_bits)

    print(f"\nTOTAL estimated QPU seconds: {total:.1f}")
    if not args.submit:
        print("dry run only - add --submit to spend QPU time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
