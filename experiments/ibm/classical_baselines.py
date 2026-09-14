"""Classical reference curves (SHA-256, MD5) for the quantum hash comparison.

    venv/bin/python experiments/ibm/classical_baselines.py

Every digest is TRUNCATED to the quantum hash width (3, 4 or 8 bits) before any
metric is computed. Without truncation the comparison is meaningless: a 256-bit
SHA-256 digest trivially beats an 8-bit quantum hash on every distribution
metric because it has 2^248 times more room. Truncation puts all constructions
on the same output space, which is the only fair way to read the avalanche and
uniformity numbers in the thesis.

Inputs are the same 16-bit messages the quantum circuits consume, encoded as
their two big-endian bytes.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = PROJECT_ROOT / "results"

INPUT_BITS = 16
WIDTHS = (3, 4, 8)
SEED = 20260908
AVALANCHE_SAMPLES = 64
# 4096 messages keeps the chi-square well powered at 8-bit truncation
# (16 expected per bucket); at 512 the test rejects on sampling noise alone.
UNIFORMITY_SAMPLES = 4096
MAX_FLIPS = 4


# ------------------------------------------------------------------------ hashing
def message_to_bytes(message_bits: str) -> bytes:
    """16-bit input bitstring -> its two big-endian bytes."""
    if len(message_bits) != INPUT_BITS or any(c not in "01" for c in message_bits):
        raise ValueError(f"expected {INPUT_BITS} bits, got {message_bits!r}")
    return int(message_bits, 2).to_bytes(INPUT_BITS // 8, "big")


def truncate_digest(digest_bytes: bytes, width: int) -> str:
    """First `width` bits of a digest, MSB first."""
    if width > len(digest_bytes) * 8:
        raise ValueError("width exceeds digest size")
    as_int = int.from_bytes(digest_bytes, "big")
    shift = len(digest_bytes) * 8 - width
    return format(as_int >> shift, f"0{width}b")


def sha256_bits(message_bits: str, width: int) -> str:
    return truncate_digest(hashlib.sha256(message_to_bytes(message_bits)).digest(), width)


def md5_bits(message_bits: str, width: int) -> str:
    return truncate_digest(hashlib.md5(message_to_bytes(message_bits)).digest(), width)


ALGORITHMS = {"sha256": sha256_bits, "md5": md5_bits}


# ------------------------------------------------------------------------ metrics
def _hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))


def _random_message(rng: random.Random) -> str:
    return "".join(rng.choice("01") for _ in range(INPUT_BITS))


def avalanche(hash_fn, width: int, max_flips: int = MAX_FLIPS,
              samples: int = AVALANCHE_SAMPLES, seed: int = SEED) -> dict:
    """Mean output distance when 1..max_flips input bits are flipped."""
    rng = random.Random(seed)
    per_flip = []
    for flips in range(1, max_flips + 1):
        distances = []
        for _ in range(samples):
            msg = _random_message(rng)
            digest = hash_fn(msg, width)
            positions = rng.sample(range(INPUT_BITS), flips)
            mutated = list(msg)
            for p in positions:
                mutated[p] = "1" if mutated[p] == "0" else "0"
            distances.append(_hamming(digest, hash_fn("".join(mutated), width)))
        mean = statistics.mean(distances)
        per_flip.append({
            "flips": flips,
            "mean_bits": mean,
            "std_bits": statistics.stdev(distances) if len(distances) > 1 else 0.0,
            "normalised": mean / width,
        })

    # Strict avalanche criterion: per input bit, over independent messages.
    rng = random.Random(seed + 1)
    per_bit = []
    for position in range(INPUT_BITS):
        distances = []
        for _ in range(samples):
            msg = _random_message(rng)
            mutated = list(msg)
            mutated[position] = "1" if mutated[position] == "0" else "0"
            distances.append(_hamming(hash_fn(msg, width),
                                      hash_fn("".join(mutated), width)))
        per_bit.append({
            "input_bit": position,
            "mean_bits": statistics.mean(distances),
            "normalised": statistics.mean(distances) / width,
        })

    return {
        "width": width,
        "samples_per_flip_count": samples,
        "max_flips": max_flips,
        "seed": seed,
        "per_flip_count": per_flip,
        "per_input_bit": per_bit,
        "one_flip_normalised": per_flip[0]["normalised"],
        "ideal_normalised": 0.5,
    }


def uniformity(hash_fn, width: int, samples: int = UNIFORMITY_SAMPLES,
               seed: int = SEED) -> dict:
    from scipy.stats import chi2

    rng = random.Random(seed + 2)
    counts: dict[str, int] = {}
    for _ in range(samples):
        digest = hash_fn(_random_message(rng), width)
        counts[digest] = counts.get(digest, 0) + 1

    buckets = 1 << width
    expected = samples / buckets
    stat = sum((counts.get(format(v, f"0{width}b"), 0) - expected) ** 2 / expected
               for v in range(buckets))
    dof = buckets - 1
    crit = float(chi2.ppf(0.95, dof))
    entropy = -sum((c / samples) * math.log2(c / samples) for c in counts.values() if c)
    return {
        "width": width,
        "samples": samples,
        "seed": seed,
        "buckets": buckets,
        "chi_square": stat,
        "dof": dof,
        "critical_value_95": crit,
        "p_value": float(chi2.sf(stat, dof)),
        "passes_uniformity": bool(stat <= crit),
        "entropy_bits": entropy,
        "entropy_ideal_bits": float(width),
        "distinct_outputs": len(counts),
        "counts": counts,
    }


def baseline_table(widths=WIDTHS) -> dict:
    table: dict[str, dict[str, dict]] = {}
    for name, fn in ALGORITHMS.items():
        table[name] = {}
        for width in widths:
            table[name][str(width)] = {
                "avalanche": avalanche(fn, width),
                "uniformity": uniformity(fn, width),
            }
    return table


def main() -> int:
    table = baseline_table()
    payload = {
        "description": "SHA-256 / MD5 truncated to the quantum hash widths",
        "input_bits": INPUT_BITS,
        "widths": list(WIDTHS),
        "seed": SEED,
        "avalanche_samples": AVALANCHE_SAMPLES,
        "uniformity_samples": UNIFORMITY_SAMPLES,
        "max_flips": MAX_FLIPS,
        "table": table,
    }
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    out = RESULTS_ROOT / "classical_baselines.json"
    out.write_text(json.dumps(payload, indent=2))

    hdr = (f"{'algo':8s} {'width':>5s} {'1-flip':>7s} {'2-flip':>7s} {'4-flip':>7s} "
           f"{'chi2':>8s} {'crit95':>7s} {'pass':>5s} {'H':>6s} {'distinct':>8s}")
    print(hdr)
    print("-" * len(hdr))
    for algo, widths in table.items():
        for width, data in widths.items():
            flips = {r["flips"]: r["normalised"] for r in data["avalanche"]["per_flip_count"]}
            u = data["uniformity"]
            print(f"{algo:8s} {width:>5s} {flips[1]:7.3f} {flips[2]:7.3f} {flips[4]:7.3f} "
                  f"{u['chi_square']:8.2f} {u['critical_value_95']:7.2f} "
                  f"{str(u['passes_uniformity']):>5s} {u['entropy_bits']:6.3f} "
                  f"{u['distinct_outputs']:8d}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
