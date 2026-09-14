"""Hardware run of the three quantum hash constructions at 3, 4 and 8 bits.

    venv/bin/python experiments/ibm/exp_hashing.py               # dry run
    venv/bin/python experiments/ibm/exp_hashing.py --submit       # ibm_fez

Constructions (all consume the same 16-bit input space, so the comparison is
apples-to-apples):
  grover      GroverHash            - oracle marks the block index itself
  feistel     GroverNonLinearHash   - oracle marks f(x), f a Feistel permutation
  simple_xor  SimpleXORHash         - parity kickback, no amplification

Metrics per (construction, width):
  fidelity       Hellinger fidelity + total variation of each message's output
                 distribution against the noiseless simulator - i.e. how much
                 of the hash survives the device.
  avalanche      single input-bit flips. Two estimators: the strict top-1
                 hash distance (what the protocol actually uses) and the
                 distribution-level expected distance E[HD] over the sampled
                 distributions, which does not collapse to a coin flip when
                 noise flattens the peak.
  uniformity     chi-square over all 2^n buckets of the pooled shot
                 distribution, plus Shannon entropy and distinct top-1 count.
  determinism    top-1 probability margin, which is what decides whether the
                 hash is stable across repeats.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ibm.common import (  # noqa: E402
    circuit_metrics,
    estimate_qpu_seconds,
    assert_budget,
    hamming,
    hellinger_fidelity,
    mean_std,
    open_run,
    run_ideal,
    run_sampler,
    shannon_entropy,
    top_bitstring,
    total_variation,
    transpile_isa,
)
from quantum_circuits.grover_hash import GroverHash, GroverNonLinearHash  # noqa: E402
from quantum_circuits.simple_xor_hash import INPUT_BITS, SimpleXORHash  # noqa: E402

EXPERIMENT = "hashing"
WIDTHS = (3, 4, 8)
# Grover iteration counts as used throughout the thesis benchmarks
# (benchmarks/compare_uniformity_hamming.py).
ITERATIONS = {3: 2, 4: 3, 8: 2}
N_MESSAGES = 12
# Every input bit is flipped: the Grover constructions derive their oracle
# target as int(block, 2) % 2**width, which silently discards the high bits of
# each 8-bit block, so a per-bit profile is the only way to see which input
# bits actually reach the digest.
FLIP_POSITIONS = tuple(range(INPUT_BITS))
MULTI_FLIP_COUNTS = (2, 3, 4)
MULTI_FLIP_SAMPLES = 4
SEED = 20260908


def build_hasher(algorithm: str, width: int):
    if algorithm == "grover":
        return GroverHash(hash_length=width, grover_iterations=ITERATIONS[width])
    if algorithm == "feistel":
        return GroverNonLinearHash(hash_length=width, grover_iterations=ITERATIONS[width])
    if algorithm == "simple_xor":
        return SimpleXORHash(hash_length=width)
    raise ValueError(algorithm)


def messages(seed: int = SEED) -> list[str]:
    rng = random.Random(seed)
    return ["".join(rng.choice("01") for _ in range(INPUT_BITS))
            for _ in range(N_MESSAGES)]


def flip_bits(bits: str, positions) -> str:
    out = list(bits)
    for p in positions:
        out[p] = "1" if out[p] == "0" else "0"
    return "".join(out)


def config_circuits(algorithm: str, width: int) -> tuple[list, list[dict]]:
    """Message circuits, every single-bit flip, and a 2/3/4-bit flip sample.

    The single-bit sweep gives the per-input-bit avalanche profile; the
    multi-flip samples give the hamming-distance-versus-flip-count curve that
    the classical SHA-256/MD5 baselines are measured on.
    """
    hasher = build_hasher(algorithm, width)
    msgs = messages()
    circuits, index = [], []

    for i, msg in enumerate(msgs):
        qc = hasher.build_circuit(msg)
        qc.name = f"{algorithm}{width}_msg{i:02d}"
        circuits.append(qc)
        index.append({"kind": "message", "message": msg, "message_index": i,
                      "circuit_name": qc.name})

    base = msgs[0]
    for pos in FLIP_POSITIONS:
        flipped = flip_bits(base, [pos])
        qc = hasher.build_circuit(flipped)
        qc.name = f"{algorithm}{width}_flip1_b{pos:02d}"
        circuits.append(qc)
        index.append({"kind": "flip", "flip_count": 1, "flip_positions": [pos],
                      "message": flipped, "base_message": base,
                      "circuit_name": qc.name})

    rng = random.Random(SEED + 7)
    for count in MULTI_FLIP_COUNTS:
        for sample in range(MULTI_FLIP_SAMPLES):
            positions = sorted(rng.sample(range(INPUT_BITS), count))
            flipped = flip_bits(base, positions)
            qc = hasher.build_circuit(flipped)
            qc.name = f"{algorithm}{width}_flip{count}_s{sample}"
            circuits.append(qc)
            index.append({"kind": "flip", "flip_count": count,
                          "flip_positions": positions, "message": flipped,
                          "base_message": base, "circuit_name": qc.name})
    return circuits, index


# ------------------------------------------------------------------------ metrics
def normalise(counts: dict, width: int) -> dict:
    total = sum(counts.values())
    return {k[-width:]: v / total for k, v in counts.items()}


def expected_hamming(p: dict, q: dict) -> float:
    """E[HD(a,b)] for a ~ p, b ~ q. Noise-robust avalanche estimator."""
    return sum(pa * qb * hamming(a, b) for a, pa in p.items() for b, qb in q.items())


def top_margin(counts: dict) -> float:
    total = sum(counts.values())
    ordered = sorted(counts.values(), reverse=True)
    if not ordered:
        return 0.0
    second = ordered[1] if len(ordered) > 1 else 0
    return (ordered[0] - second) / total


def chi_square_uniformity(pooled: dict, width: int) -> dict:
    from scipy.stats import chi2

    buckets = 1 << width
    total = sum(pooled.values())
    expected = total / buckets
    stat = sum((pooled.get(format(v, f"0{width}b"), 0) - expected) ** 2 / expected
               for v in range(buckets))
    dof = buckets - 1
    crit = float(chi2.ppf(0.95, dof))
    return {
        "chi_square": stat,
        "dof": dof,
        "critical_value_95": crit,
        "passes_uniformity": bool(stat <= crit),
        "p_value": float(chi2.sf(stat, dof)),
        "samples": total,
        "entropy_bits": shannon_entropy(pooled),
        "entropy_ideal_bits": float(width),
        "distinct_outputs": len([1 for v in pooled.values() if v]),
        "buckets": buckets,
    }


def analyse(records: list[dict], index: list[dict], width: int,
            reference: list[dict] | None = None) -> dict:
    by_name = {r["circuit_name"]: r for r in records}
    ref_by_name = {r["circuit_name"]: r for r in (reference or [])}

    per_message, pooled = [], {}
    for entry in index:
        rec = by_name[entry["circuit_name"]]
        counts = {k[-width:]: v for k, v in rec["counts"].items()}
        top = top_bitstring(counts)
        row = {
            **entry,
            "top_hash": top,
            "top_probability": counts[top] / sum(counts.values()),
            "top_margin": top_margin(counts),
            "entropy_bits": shannon_entropy(counts),
            "counts": counts,
        }
        if entry["circuit_name"] in ref_by_name:
            ref_counts = {k[-width:]: v for k, v in ref_by_name[entry["circuit_name"]]["counts"].items()}
            row["ideal_top_hash"] = top_bitstring(ref_counts)
            row["fidelity_vs_ideal"] = hellinger_fidelity(counts, ref_counts)
            row["tvd_vs_ideal"] = total_variation(counts, ref_counts)
            row["top1_matches_ideal"] = row["top_hash"] == row["ideal_top_hash"]
        per_message.append(row)
        if entry["kind"] == "message":
            for k, v in counts.items():
                pooled[k] = pooled.get(k, 0) + v

    msg_rows = [r for r in per_message if r["kind"] == "message"]
    flip_rows = [r for r in per_message if r["kind"] == "flip"]
    base_row = msg_rows[0]
    base_dist = normalise(base_row["counts"], width)

    rows_by_flip: dict[int, list] = {}
    per_position = []
    for row in flip_rows:
        d_top = hamming(base_row["top_hash"], row["top_hash"])
        d_exp = expected_hamming(base_dist, normalise(row["counts"], width))
        row["hamming_top1"] = d_top
        row["hamming_expected"] = d_exp
        rows_by_flip.setdefault(row["flip_count"], []).append(row)
        if row["flip_count"] == 1:
            per_position.append({
                "flip_position": row["flip_positions"][0],
                "top_hash": row["top_hash"],
                "hamming_top1": d_top,
                "hamming_expected": d_exp,
            })

    per_flip_count = []
    for count in sorted(rows_by_flip):
        rows = rows_by_flip[count]
        t_mean, t_std = mean_std([r["hamming_top1"] for r in rows])
        e_mean, e_std = mean_std([r["hamming_expected"] for r in rows])
        per_flip_count.append({
            "flips": count,
            "samples": len(rows),
            "top1_mean_bits": t_mean,
            "top1_std_bits": t_std,
            "top1_normalised": t_mean / width,
            "expected_mean_bits": e_mean,
            "expected_std_bits": e_std,
            "expected_normalised": e_mean / width,
        })

    single = rows_by_flip.get(1, [])
    top1_mean, top1_std = mean_std([r["hamming_top1"] for r in single])
    exp_mean, exp_std = mean_std([r["hamming_expected"] for r in single])
    fid = [r["fidelity_vs_ideal"] for r in per_message if "fidelity_vs_ideal" in r]
    tvd = [r["tvd_vs_ideal"] for r in per_message if "tvd_vs_ideal" in r]
    match = [r["top1_matches_ideal"] for r in per_message if "top1_matches_ideal" in r]

    out = {
        "width": width,
        "avalanche": {
            "flip_positions": list(FLIP_POSITIONS),
            "per_position": per_position,
            "per_flip_count": per_flip_count,
            "top1_mean_bits": top1_mean,
            "top1_std_bits": top1_std,
            "top1_normalised": top1_mean / width,
            "expected_mean_bits": exp_mean,
            "expected_std_bits": exp_std,
            "expected_normalised": exp_mean / width,
            "ideal_normalised": 0.5,
            "dead_input_bits": [p["flip_position"] for p in per_position
                                if p["hamming_top1"] == 0],
        },
        "uniformity": chi_square_uniformity(pooled, width),
        "determinism": {
            "mean_top_probability": mean_std([r["top_probability"] for r in msg_rows])[0],
            "mean_top_margin": mean_std([r["top_margin"] for r in msg_rows])[0],
            "distinct_top1_hashes": len({r["top_hash"] for r in msg_rows}),
            "n_messages": len(msg_rows),
            "collision_rate": 1 - len({r["top_hash"] for r in msg_rows}) / len(msg_rows),
        },
        "per_circuit": per_message,
    }
    if fid:
        out["vs_ideal"] = {
            "mean_hellinger_fidelity": mean_std(fid)[0],
            "std_hellinger_fidelity": mean_std(fid)[1],
            "mean_total_variation": mean_std(tvd)[0],
            "top1_agreement_rate": sum(match) / len(match),
        }
    return out


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true", help="run on the QPU")
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--shots-8bit", type=int, default=None,
                        help="separate shot count for the deep 8-bit circuits")
    parser.add_argument("--algorithms", default="grover,feistel,simple_xor")
    parser.add_argument("--widths", default="3,4,8")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--reserve", type=float, default=60.0)
    args = parser.parse_args(argv)

    ctx = open_run(run_id=args.run_id)
    algorithms = args.algorithms.split(",")
    widths = [int(w) for w in args.widths.split(",")]

    grand_total = 0.0
    for algorithm in algorithms:
        for width in widths:
            shots = args.shots_8bit if (width == 8 and args.shots_8bit) else args.shots
            name = f"{algorithm}_{width}bit"
            print(f"\n=== {name} (iterations="
                  f"{ITERATIONS[width] if algorithm != 'simple_xor' else 'n/a'}, shots={shots})")

            circuits, index = config_circuits(algorithm, width)
            isa, isa_metrics = transpile_isa(circuits, ctx.backend)
            estimate = estimate_qpu_seconds(isa, shots, ctx.backend)
            grand_total += estimate["estimated_qpu_seconds"]
            depths = [m["depth"] for m in isa_metrics]
            two_q = [m["two_qubit_gates"] for m in isa_metrics]
            print(f"  logical qubits={circuits[0].num_qubits} circuits={len(circuits)} "
                  f"isa_depth={min(depths)}-{max(depths)} 2q={min(two_q)}-{max(two_q)}")
            print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s "
                  f"(max circuit {estimate['max_circuit_duration_s'] * 1e6:.0f} us)")

            ideal = run_ideal(circuits, shots)
            ideal_analysis = analyse(ideal, index, width)
            print(f"  ideal: avalanche top1={ideal_analysis['avalanche']['top1_normalised']:.3f} "
                  f"expected={ideal_analysis['avalanche']['expected_normalised']:.3f} "
                  f"entropy={ideal_analysis['uniformity']['entropy_bits']:.2f}/{width} "
                  f"distinct_top1={ideal_analysis['determinism']['distinct_top1_hashes']}"
                  f"/{N_MESSAGES}")

            payload_common = {
                "run_id": ctx.run_id,
                "backend": ctx.backend_name,
                "algorithm": algorithm,
                "width": width,
                "grover_iterations": ITERATIONS[width] if algorithm != "simple_xor" else None,
                "feistel_rounds": getattr(build_hasher(algorithm, width), "rounds", None),
                "shots": shots,
                "input_bits": INPUT_BITS,
                "messages": messages(),
                "seed": SEED,
                "circuit_index": index,
                "logical_metrics": [circuit_metrics(c) for c in circuits],
                "isa_metrics": isa_metrics,
                "estimate": estimate,
            }
            ctx.save(EXPERIMENT, f"{name}_ideal",
                     {**payload_common, "source": "AerSimulator (noiseless)",
                      "analysis": ideal_analysis, "records": ideal})

            if args.submit:
                assert_budget(estimate, reserve_seconds=args.reserve)
                records = run_sampler(ctx, isa, shots, tag=name,
                                      metadata={"algorithm": algorithm, "width": width})
                analysis = analyse(records, index, width, reference=ideal)
                print(f"  hardware: fidelity={analysis['vs_ideal']['mean_hellinger_fidelity']:.3f} "
                      f"top1_agreement={analysis['vs_ideal']['top1_agreement_rate']:.2f} "
                      f"avalanche_expected={analysis['avalanche']['expected_normalised']:.3f}")
                ctx.save(EXPERIMENT, name,
                         {**payload_common, "source": f"QPU {ctx.backend_name}",
                          "analysis": analysis, "records": records})

    print(f"\nTOTAL estimated QPU seconds for this selection: {grand_total:.1f}")
    if not args.submit:
        print("dry run only - add --submit to spend QPU time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
