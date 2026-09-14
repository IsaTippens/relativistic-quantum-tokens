"""One BB84 exchange on hardware: Alice prepares, Bob measures, 1000 shots.

    venv/bin/python experiments/ibm/exp_bb84.py            # dry run
    venv/bin/python experiments/ibm/exp_bb84.py --submit   # ibm_fez

Each of the --nbits qubits is one independent key position (no entanglement
between positions), so a single wide circuit is one full exchange and every
shot is an independent repetition of it.

Reported two ways, because both matter for the thesis:
  single run   shot 0 taken as one physical exchange: sifted key, its QBER.
  1000-shot    per-position error probabilities, mean matched-basis QBER with
               its spread, and the mismatched-basis control (must sit near 0.5,
               proving the basis choice is doing something), plus the split by
               preparation basis and the per-qubit errors so one bad physical
               qubit is visible rather than smeared into the average.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister  # noqa: E402

from experiments.ibm.common import (  # noqa: E402
    assert_budget,
    circuit_metrics,
    estimate_qpu_seconds,
    mean_std,
    open_run,
    run_ideal,
    run_sampler,
    transpile_isa,
)

EXPERIMENT = "bb84"
DEFAULT_NBITS = 64
DEFAULT_SHOTS = 1000
DEFAULT_SEED = 20260908
QBER_SECURITY_THRESHOLD = 0.11


def draw_protocol(nbits: int, seed: int) -> dict:
    rng = random.Random(seed)
    return {
        "alice_bits": [rng.randint(0, 1) for _ in range(nbits)],
        "alice_bases": [rng.choice("ZX") for _ in range(nbits)],
        "bob_bases": [rng.choice("ZX") for _ in range(nbits)],
    }


def build_circuit(protocol: dict, nbits: int) -> QuantumCircuit:
    qr = QuantumRegister(nbits, "q")
    cr = ClassicalRegister(nbits, "c")
    qc = QuantumCircuit(qr, cr, name=f"bb84_{nbits}bit")

    for i in range(nbits):
        # Alice prepares |0>, |1>, |+> or |->
        if protocol["alice_bits"][i]:
            qc.x(qr[i])
        if protocol["alice_bases"][i] == "X":
            qc.h(qr[i])
    qc.barrier()
    for i in range(nbits):
        # Bob rotates into his basis and measures
        if protocol["bob_bases"][i] == "X":
            qc.h(qr[i])
    qc.measure(qr, cr)
    return qc


def bits_of(bitstring: str, nbits: int) -> list[int]:
    """Counts/bitstring keys are MSB-first over the register."""
    ordered = bitstring.replace(" ", "")[::-1]
    return [int(ordered[i]) for i in range(nbits)]


def analyse(record: dict, protocol: dict, nbits: int) -> dict:
    alice_bits = protocol["alice_bits"]
    alice_bases = protocol["alice_bases"]
    bob_bases = protocol["bob_bases"]
    matched = [i for i in range(nbits) if alice_bases[i] == bob_bases[i]]
    mismatched = [i for i in range(nbits) if alice_bases[i] != bob_bases[i]]

    shots = record["bitstrings"]
    per_shot_bits = [bits_of(s, nbits) for s in shots]
    n_shots = len(per_shot_bits)

    # --- per-position error probability over every shot
    errors = [0] * nbits
    for bits in per_shot_bits:
        for i in range(nbits):
            if bits[i] != alice_bits[i]:
                errors[i] += 1
    per_position = [
        {
            "position": i,
            "alice_bit": alice_bits[i],
            "alice_basis": alice_bases[i],
            "bob_basis": bob_bases[i],
            "bases_match": alice_bases[i] == bob_bases[i],
            "error_rate": errors[i] / n_shots,
        }
        for i in range(nbits)
    ]

    matched_rates = [per_position[i]["error_rate"] for i in matched]
    mismatched_rates = [per_position[i]["error_rate"] for i in mismatched]
    z_rates = [per_position[i]["error_rate"] for i in matched if alice_bases[i] == "Z"]
    x_rates = [per_position[i]["error_rate"] for i in matched if alice_bases[i] == "X"]

    matched_mean, matched_std = mean_std(matched_rates)

    # --- the single physical exchange: shot 0
    shot0 = per_shot_bits[0]
    sifted_bob = [shot0[i] for i in matched]
    sifted_alice = [alice_bits[i] for i in matched]
    single_errors = sum(a != b for a, b in zip(sifted_alice, sifted_bob))
    sifted_str = "".join(str(b) for b in sifted_bob)
    alice_str = "".join(str(b) for b in sifted_alice)

    return {
        "nbits": nbits,
        "shots": n_shots,
        "sifting": {
            "matched_positions": matched,
            "n_matched": len(matched),
            "sift_rate": len(matched) / nbits,
            "expected_sift_rate": 0.5,
        },
        "single_run": {
            "shot_index": 0,
            "sifted_key_bob": sifted_str,
            "sifted_key_alice": alice_str,
            "sifted_key_hex": f"{int(sifted_str, 2):0{(len(sifted_str) + 3) // 4}X}" if sifted_str else "",
            "sifted_length": len(sifted_str),
            "errors": single_errors,
            "qber": single_errors / len(matched) if matched else 0.0,
            "keys_identical": sifted_str == alice_str,
        },
        "averaged": {
            "matched_qber_mean": matched_mean,
            "matched_qber_std": matched_std,
            "matched_qber_min": min(matched_rates) if matched_rates else 0.0,
            "matched_qber_max": max(matched_rates) if matched_rates else 0.0,
            "mismatched_qber_mean": mean_std(mismatched_rates)[0],
            "mismatched_expected": 0.5,
            "z_basis_qber_mean": mean_std(z_rates)[0],
            "x_basis_qber_mean": mean_std(x_rates)[0],
            "worst_positions": sorted(
                ({"position": p["position"], "error_rate": p["error_rate"]}
                 for p in per_position if p["bases_match"]),
                key=lambda d: -d["error_rate"])[:5],
        },
        "security": {
            "threshold": QBER_SECURITY_THRESHOLD,
            "matched_qber": matched_mean,
            "below_threshold": matched_mean <= QBER_SECURITY_THRESHOLD,
            "verdict": ("key usable after error correction"
                        if matched_mean <= QBER_SECURITY_THRESHOLD
                        else "QBER above the 11% BB84 bound: abort the key"),
        },
        "per_position": per_position,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    parser.add_argument("--nbits", type=int, default=DEFAULT_NBITS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--reserve", type=float, default=60.0)
    args = parser.parse_args(argv)

    ctx = open_run(run_id=args.run_id)
    protocol = draw_protocol(args.nbits, args.seed)
    circuit = build_circuit(protocol, args.nbits)
    isa, isa_metrics = transpile_isa([circuit], ctx.backend)
    estimate = estimate_qpu_seconds(isa, args.shots, ctx.backend)

    print(f"\n=== bb84 single exchange ({args.nbits} positions, {args.shots} shots)")
    print(f"  isa depth={isa_metrics[0]['depth']} ops={isa_metrics[0]['ops']}")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    # 64 independent qubits: H/X/measure only, so the stabilizer simulator
    # handles the reference exactly (a 2^64 statevector is not an option).
    ideal = run_ideal([circuit], args.shots, method="stabilizer")
    ideal_analysis = analyse(ideal[0], protocol, args.nbits)
    print(f"  ideal: sift_rate={ideal_analysis['sifting']['sift_rate']:.3f} "
          f"matched_qber={ideal_analysis['averaged']['matched_qber_mean']:.4f} "
          f"mismatched_qber={ideal_analysis['averaged']['mismatched_qber_mean']:.3f} "
          f"single_run_qber={ideal_analysis['single_run']['qber']:.4f}")

    assert ideal_analysis["averaged"]["matched_qber_mean"] == 0.0, \
        "noiseless matched-basis QBER must be exactly zero"
    assert abs(ideal_analysis["averaged"]["mismatched_qber_mean"] - 0.5) < 0.06, \
        "mismatched-basis QBER must sit at 0.5"
    assert ideal_analysis["single_run"]["keys_identical"], \
        "noiseless sifted keys must agree"

    payload = {
        "run_id": ctx.run_id,
        "backend": ctx.backend_name,
        "nbits": args.nbits,
        "shots": args.shots,
        "seed": args.seed,
        "protocol": protocol,
        "logical_metrics": circuit_metrics(circuit),
        "isa_metrics": isa_metrics,
        "estimate": estimate,
    }
    ctx.save(EXPERIMENT, "single_exchange_ideal",
             {**payload, "source": "AerSimulator (noiseless)",
              "analysis": ideal_analysis, "record": ideal[0]})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, args.shots, tag="bb84_single_exchange",
                              metadata={"nbits": args.nbits, "seed": args.seed})
        analysis = analyse(records[0], protocol, args.nbits)
        print(f"  hardware: matched_qber={analysis['averaged']['matched_qber_mean']:.4f} "
              f"+/-{analysis['averaged']['matched_qber_std']:.4f} "
              f"mismatched={analysis['averaged']['mismatched_qber_mean']:.3f} "
              f"single_run_qber={analysis['single_run']['qber']:.4f} "
              f"-> {analysis['security']['verdict']}")
        ctx.save(EXPERIMENT, "single_exchange",
                 {**payload, "source": f"QPU {ctx.backend_name}",
                  "analysis": analysis, "record": records[0]})
    else:
        print("dry run only - add --submit to spend QPU time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
