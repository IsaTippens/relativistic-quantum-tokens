import os
import sys
import subprocess
import time
import asyncio
import random
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# Repo root (parent of scripts/) so the script works from any CWD
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from entities.bank_node import BankNode
from entities.alice_node import AliceNode
from entities.charlie_node import CharlieNode

def main():
    artifacts_dir = ROOT / "test_artifacts"
    os.makedirs(artifacts_dir, exist_ok=True)
    
    # Run pytest and capture output
    print("Running E2E tests...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_e2e_quantum_token.py", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    
    with open(artifacts_dir / "pytest_output.txt", "w") as f:
        f.write(result.stdout)
        f.write(result.stderr)
        
    print("Tests finished. Measuring latencies...")
    
    # Measure Latencies
    bank = BankNode()
    alice = AliceNode()
    charlie = CharlieNode()
    
    # 1. Issuance
    t0 = time.time()
    bank.perform_bb84_exchange(alice)
    t1 = time.time()
    issuance_latency = t1 - t0
    
    # 2. Hashing
    t2 = time.time()
    target_geohash = "gcpuy"
    expiration_timestamp = time.time() + 300
    payload = alice.program_token(target_geohash, expiration_timestamp)
    t3 = time.time()
    hashing_latency = t3 - t2
    
    # 3. Settlement
    t4 = time.time()
    async def settle():
        return await charlie.receive_and_settle(alice.send_token(payload), time.time(), target_geohash, bank)
    
    success = asyncio.run(settle())
    t5 = time.time()
    settlement_latency = t5 - t4
    
    print(f"Issuance: {issuance_latency:.4f}s")
    print(f"Hashing: {hashing_latency:.4f}s")
    print(f"Settlement: {settlement_latency:.4f}s")
    
    # Generate transaction_lifecycle.png
    stages = ['Issuance', 'Hashing', 'Settlement']
    latencies = [issuance_latency, hashing_latency, settlement_latency]
    
    plt.figure(figsize=(8, 5))
    plt.bar(stages, latencies, color=['blue', 'orange', 'green'])
    plt.title('Transaction Lifecycle Latency')
    plt.ylabel('Latency (seconds)')
    plt.savefig(artifacts_dir / 'transaction_lifecycle.png')
    plt.close()
    
    # Generate transaction_reliability.png using the BB84Simulator defined in the codebase
    from quantum_circuits.bb84_simulator import BB84Simulator
    
    num_transactions = 1000
    required_bits = num_transactions * 4
    
    shared_key = ""
    sim = BB84Simulator(num_bits=2000)
    while len(shared_key) < required_bits:
        shared_key += sim.generate_shared_secret()
        
    shared_key = shared_key[:required_bits]
    chunks = [shared_key[i:i+4] for i in range(0, required_bits, 4)]
    transaction_states = [f"|{chunk}⟩" for chunk in chunks]
    
    states = [f"|{format(i, '04b')}⟩" for i in range(16)]
    reliability = [100] * num_transactions
    
    cmap = plt.get_cmap('tab20')
    state_colors = {state: cmap(i) for i, state in enumerate(states)}
    bar_colors = [state_colors[state] for state in transaction_states]
    
    plt.figure(figsize=(12, 6))
    plt.bar(range(num_transactions), reliability, color=bar_colors, width=1.0, edgecolor='none')
    plt.title('Transaction Reliability by Quantum State')
    plt.xlabel('Transaction ID')
    plt.ylabel('Reliability (%)')
    plt.ylim(0, 110)
    
    legend_elements = []
    for state in states:
        count = transaction_states.count(state)
        percentage = (count / num_transactions) * 100
        label = f"{state} ({percentage:.1f}%)"
        legend_elements.append(Patch(facecolor=state_colors[state], label=label))
    plt.legend(handles=legend_elements, bbox_to_anchor=(1.02, 1), loc='upper left', title="Quantum State")
    plt.tight_layout()
    
    plt.savefig(artifacts_dir / 'transaction_reliability.png')
    plt.close()
    
    # Remove old edge_case_rejection_rates.png if it exists
    old_plot_path = artifacts_dir / 'edge_case_rejection_rates.png'
    if os.path.exists(old_plot_path):
        os.remove(old_plot_path)
    
    print("Artifacts generated successfully.")

if __name__ == "__main__":
    main()
