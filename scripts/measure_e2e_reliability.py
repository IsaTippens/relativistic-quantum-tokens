"""Measure end-to-end transaction reliability and archive the result.

Runs the full happy-path lifecycle (BB84 exchange, AAH programming, settlement)
once per transaction, each with a fresh bank, wallet and merchant, and writes
one record per transaction to test_artifacts/e2e_reliability.json.
scripts/generate_artifacts.py renders transaction_reliability.png from that
file, so the figure reports measured outcomes rather than assumed ones.

Usage:
    python scripts/measure_e2e_reliability.py           # 1000 transactions
    python scripts/measure_e2e_reliability.py -n 50     # quick check
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Repo root (parent of scripts/) so the script works from any CWD
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from entities.bank_node import BankNode
from entities.alice_node import AliceNode
from entities.charlie_node import CharlieNode

TARGET_GEOHASH = "gcpuy"
TOKEN_LIFETIME_S = 300


async def run_transaction(hash_length: int) -> dict:
    """Execute one valid transaction and report its outcome."""
    bank = BankNode()
    alice = AliceNode()
    charlie = CharlieNode()

    started = time.time()
    bank.perform_bb84_exchange(alice)
    shared_secret = alice.shared_secret
    payload = alice.program_token(
        TARGET_GEOHASH, time.time() + TOKEN_LIFETIME_S, hash_length=hash_length)
    settled = await charlie.receive_and_settle(
        alice.send_token(payload), time.time(), TARGET_GEOHASH, bank,
        hash_length=hash_length)

    return {
        "success": bool(settled),
        "key_slice": shared_secret[:4],
        "latency_s": time.time() - started,
    }


async def main():
    parser = argparse.ArgumentParser(description="Measure E2E transaction reliability")
    parser.add_argument("-n", "--transactions", type=int, default=1000)
    parser.add_argument("--hash-length", type=int, default=4)
    parser.add_argument("-o", "--output", type=Path,
                        default=ROOT / "test_artifacts" / "e2e_reliability.json")
    args = parser.parse_args()

    records = []
    started = time.time()
    for i in range(args.transactions):
        records.append(await run_transaction(args.hash_length))
        if (i + 1) % 50 == 0:
            settled = sum(record["success"] for record in records)
            print(f"{i + 1}/{args.transactions} transactions, {settled} settled, "
                  f"{time.time() - started:.0f}s elapsed", flush=True)

    settled = sum(record["success"] for record in records)
    counts = {}
    for record in records:
        counts[record["key_slice"]] = counts.get(record["key_slice"], 0) + 1

    result = {
        "measured_by": "scripts/measure_e2e_reliability.py",
        "hash_length": args.hash_length,
        "geohash": TARGET_GEOHASH,
        "token_lifetime_s": TOKEN_LIFETIME_S,
        "n": args.transactions,
        "settled": settled,
        "failed": args.transactions - settled,
        "mean_latency_s": sum(record["latency_s"] for record in records) / len(records),
        "key_slice_counts": dict(sorted(counts.items())),
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(f"{settled}/{args.transactions} settled in {time.time() - started:.0f}s "
          f"-> {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
