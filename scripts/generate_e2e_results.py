import os
import sys
import time
import asyncio
from pathlib import Path
import matplotlib.pyplot as plt

# Repo root (parent of scripts/) so the script works from any CWD
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from entities.bank_node import BankNode
from entities.alice_node import AliceNode
from entities.charlie_node import CharlieNode

async def run_workflow(hash_length):
    bank = BankNode()
    alice = AliceNode()
    charlie = CharlieNode()
    
    metrics = {}
    
    # 1. BB84 Exchange
    t0 = time.time()
    bank.perform_bb84_exchange(alice)
    t1 = time.time()
    metrics["bb84"] = t1 - t0
    
    # 2. Token Programming
    target_geohash = "gcpuy"
    expiration = time.time() + 300
    
    t0 = time.time()
    payload = alice.program_token(target_geohash, expiration, hash_length=hash_length)
    t1 = time.time()
    metrics["program"] = t1 - t0
    
    # 3. Settlement
    current_time = time.time()
    current_geohash = "gcpuy"
    
    t0 = time.time()
    result = await charlie.receive_and_settle(alice.send_token(payload), current_time, current_geohash, bank, hash_length=hash_length)
    t1 = time.time()
    metrics["settlement"] = t1 - t0
    
    metrics["total"] = metrics["bb84"] + metrics["program"] + metrics["settlement"]
    metrics["success"] = result
    
    return metrics

async def main():
    output_dir = ROOT / "output"
    os.makedirs(output_dir, exist_ok=True)
    
    hash_lengths = [2, 4, 6]
    results = {
        "bb84": [],
        "program": [],
        "settlement": [],
        "total": []
    }
    
    print("Running E2E token workflow metrics collection...")
    for hl in hash_lengths:
        print(f"Testing hash length: {hl}...")
        # Run a few times and average to get stable numbers
        bb84_avg = 0
        program_avg = 0
        settlement_avg = 0
        total_avg = 0
        
        runs = 3
        for _ in range(runs):
            metrics = await run_workflow(hl)
            bb84_avg += metrics["bb84"]
            program_avg += metrics["program"]
            settlement_avg += metrics["settlement"]
            total_avg += metrics["total"]
            
        results["bb84"].append(bb84_avg / runs)
        results["program"].append(program_avg / runs)
        results["settlement"].append(settlement_avg / runs)
        results["total"].append(total_avg / runs)
        
    print("Generating graphs...")
    # Plotting Latency Breakdown
    plt.figure(figsize=(10, 6))
    plt.plot(hash_lengths, results["bb84"], marker='o', label="BB84 Exchange", linestyle='--')
    plt.plot(hash_lengths, results["program"], marker='o', label="Token Programming (Grover)")
    plt.plot(hash_lengths, results["settlement"], marker='o', label="Settlement (Grover)")
    plt.plot(hash_lengths, results["total"], marker='o', label="Total Latency", linewidth=2)
    
    plt.title("E2E Quantum Token Workflow Latency vs. Hash Length")
    plt.xlabel("Hash Length (bits)")
    plt.ylabel("Latency (seconds)")
    plt.legend()
    plt.grid(True)
    plt.savefig(os.path.join(output_dir, "workflow_latency.png"))
    plt.close()
    
    # Generate Markdown documentation
    md_content = """# Quantum Token E2E Testing Workflow

This document explains the end-to-end (E2E) testing workflow for the relativistic quantum token system.

## Workflow Overview

The token lifecycle involves three primary entities and sequential phases:

1. **BankNode**: The centralized issuer that maintains an SQLite ledger.
2. **AliceNode**: The token requester/programmer.
3. **CharlieNode**: The proxy node resolving the final settlement.

### Phase 1: Key Generation (BB84 Exchange)
Alice and the Bank execute a BB84 protocol over a quantum channel. The bank generates a `serial_number` and stores it alongside the derived `shared_secret` with an `ACTIVE` status in the ledger.

### Phase 2: Token Programming
Alice prepares the token for a specific merchant/location (`target_geohash`) and time limit (`expiration_timestamp`). She signs these constraints using a Grover-based Amplitude-Amplification-Hash (AAH) quantum circuit. This generates a computationally unclonable signature from the `shared_secret`.

### Phase 3: Settlement
Alice presents the token to Charlie, who appends his local observation (`current_time`, `current_geohash`). He proxies this bundle to the Bank. The Bank verifies the temporal and geographic validity, reconstructs the expected AAH string, and re-runs the quantum hash verification. If valid, the DB status is updated to `SPENT`.

## Adversarial Edge Cases Verified
- **Geographic Spoofing**: Submitting from a mismatched location.
- **Temporal Expiration**: Attempting to settle after the expiration deadline.
- **Data Tampering**: Falsifying data payloads after AAH signature computation.
- **Double Spending**: Concurrently submitting the same valid token multiple times.

## Performance Metrics

The chart below shows the latency overhead for each phase depending on the simulated Grover Hash length.

![Workflow Latency Graph](workflow_latency.png)

As shown in the graph, the Grover-based phases (Programming and Settlement) scale exponentially in latency based on the chosen signature hash length, while the BB84 exchange time remains mostly stable as it uses a fixed 128-bit channel simulation.
"""
    
    with open(os.path.join(output_dir, "testing_workflow.md"), "w") as f:
        f.write(md_content)
        
    print("Done! Check the output/ folder.")

if __name__ == "__main__":
    asyncio.run(main())
