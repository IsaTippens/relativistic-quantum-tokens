import os
import time
import hashlib
import random
from collections import Counter
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.spatial import distance
from quantum_circuits.grover_hash import GroverHash, GroverNonLinearHash

# Helpers
def convert_to_bytes(data):
    if not data:
        return b''
    padding_length = (8 - len(data) % 8) % 8
    padded_data = data + [0] * padding_length
    byte_array = bytearray()
    for i in range(0, len(padded_data), 8):
        byte_chunk = padded_data[i:i+8]
        byte_value = sum(bit << (7 - j) for j, bit in enumerate(byte_chunk))
        byte_array.append(byte_value)
    return bytes(byte_array)

def hex_to_binary_arr(hex_str: str) -> list[int]:
    bin_str = bin(int(hex_str, 16))[2:].zfill(len(hex_str) * 4)
    return [int(c) for c in bin_str]

def get_bin_str(data: bytes) -> str:
    if not data:
        return "0000000000000000"
    return bin(int.from_bytes(data, 'big'))[2:].zfill(len(data) * 8)[:16]

# Classical algorithms
def classical_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()

def classical_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest().upper()

# Grover streaming hashes
gh3 = GroverHash(hash_length=3, grover_iterations=2)
gh4 = GroverHash(hash_length=4, grover_iterations=3)
gh8 = GroverHash(hash_length=8, grover_iterations=2)

def grover3_hex(data: bytes) -> str:
    bin_str = get_bin_str(data)
    res = gh3.compute_hash(bin_str)
    return hex(int('0' + res, 2))[2:].upper()

def grover4_hex(data: bytes) -> str:
    bin_str = get_bin_str(data)
    res = gh4.compute_hash(bin_str)
    return hex(int(res, 2))[2:].upper()

def grover8_hex(data: bytes) -> str:
    bin_str = get_bin_str(data)
    res = gh8.compute_hash(bin_str)
    return hex(int(res, 2))[2:].zfill(2).upper()

gnh4 = GroverNonLinearHash(hash_length=4, grover_iterations=3)
gnh8 = GroverNonLinearHash(hash_length=8, grover_iterations=2)

def grover_nonlinear4_hex(data: bytes) -> str:
    bin_str = get_bin_str(data)
    res = gnh4.compute_hash(bin_str, shots=100)
    return hex(int(res, 2))[2:].upper()

def grover_nonlinear8_hex(data: bytes) -> str:
    bin_str = get_bin_str(data)
    res = gnh8.compute_hash(bin_str, shots=100)
    return hex(int(res, 2))[2:].zfill(2).upper()

# Uniformity Test
def run_uniformity_test(hash_name, hash_fn, num_samples=200, input_bit_length=64, num_categories=16):
    hex_counts = Counter()
    for _ in range(num_samples):
        bit_arr = [random.choice([0, 1]) for _ in range(input_bit_length)]
        bytes_data = convert_to_bytes(bit_arr)
        hash_val = hash_fn(bytes_data)
        for char in hash_val:
            hex_counts[char] += 1
            
    total_chars = sum(hex_counts.values())
    expected_count = total_chars / num_categories
    
    chi2_statistic = 0
    allowed_chars = [format(x, 'X') for x in range(num_categories)]
    for char in allowed_chars:
        count = hex_counts.get(char, 0)
        chi2_statistic += (count - expected_count)**2 / expected_count
        
    dof = num_categories - 1
    critical_values = {
        7: 14.067,
        15: 24.996
    }
    crit = critical_values.get(dof, 24.996)
    passed = chi2_statistic <= crit
    return chi2_statistic, dof, crit, passed, hex_counts

# Hamming Distance Test
def run_hamming_test(hash_fn, num_samples=30, message_bits=16, num_flips=5):
    avg_dists = [0.0] * num_flips
    
    for flip_idx in range(num_flips):
        flips = flip_idx + 1
        total_dist = 0.0
        count = 0
        
        for _ in range(num_samples):
            bits = [random.choice([0, 1]) for _ in range(message_bits)]
            bytes_orig = convert_to_bytes(bits)
            
            hash_orig = hash_fn(bytes_orig)
            hash_orig_bits = hex_to_binary_arr(hash_orig)
            
            modify_bits = bits.copy()
            indexes = random.sample(range(len(modify_bits)), flips)
            for idx in indexes:
                modify_bits[idx] = 1 - modify_bits[idx]
                
            bytes_mod = convert_to_bytes(modify_bits)
            
            hash_mod = hash_fn(bytes_mod)
            hash_mod_bits = hex_to_binary_arr(hash_mod)
            
            dist = distance.hamming(hash_orig_bits, hash_mod_bits)
            total_dist += dist
            count += 1
            
        avg_dists[flip_idx] = total_dist / count if count > 0 else 0.0
        
    return avg_dists

def save_plot(filename):
    os.makedirs("benchmarks", exist_ok=True)
    bench_path = os.path.join("benchmarks", filename)
    plt.savefig(bench_path, dpi=300, bbox_inches='tight')
    
    code_dir = "/home/isati/dev/uni/projects/code/hashing"
    if os.path.exists(code_dir) and os.access(code_dir, os.W_OK):
        code_path = os.path.join(code_dir, filename)
        plt.savefig(code_path, dpi=300, bbox_inches='tight')
        print(f"Saved {filename} to {bench_path} and {code_path}")
    else:
        print(f"Saved {filename} to {bench_path}")

def plot_uniformity(hex_counts, title, filename):
    total_chars = sum(hex_counts.values())
    
    has_large_chars = any(c in '89ABCDEF' for c in hex_counts.keys())
    allowed_chars = [format(x, 'X') for x in range(16 if has_large_chars else 8)]
    
    expected_count = total_chars / len(allowed_chars)
    
    data_list = []
    for char in allowed_chars:
        data_list.append({'Character': char, 'Count': hex_counts.get(char, 0)})
    hex_data = pd.DataFrame(data_list)
    
    plt.figure(figsize=(10, 6))
    sns.barplot(x='Character', y='Count', data=hex_data, color='skyblue', label='Observed')
    plt.axhline(y=expected_count, color='red', linestyle='--', label=f'Expected ({expected_count:.2f})')
    plt.xlabel("Hexadecimal Character")
    plt.ylabel("Frequency")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    save_plot(filename)
    plt.close()

def generate_classical_hamming_cache(hash_fn, max_length=100, num_flips=10, samples=5):
    cache = []
    for i in range(max_length):
        bits = [random.choice([0, 1]) for _ in range(i + 1)]
        msg = convert_to_bytes(bits)
        original_hash = hash_fn(msg)
        original_hash_bits = hex_to_binary_arr(original_hash)

        dists = [0.0] * num_flips

        for j in range(min(i + 1, num_flips)):
            total_samples = 0
            for k in range(samples):
                modify_bits = bits.copy()
                indexes = random.sample(range(len(modify_bits)), j + 1)
                for index in indexes:
                    modify_bits[index] = 1 - modify_bits[index]
                modify_msg = convert_to_bytes(modify_bits)
                modified_hash = hash_fn(modify_msg)
                modified_hash_bits = hex_to_binary_arr(modified_hash)

                dist = distance.hamming(original_hash_bits, modified_hash_bits)
                total_samples += dist
            avg_dist = total_samples / samples
            dists[j] = avg_dist
        cache.append(dists)
    
    columns = [f'{x + 1} Bit flip' for x in range(num_flips)]
    df = pd.DataFrame(cache, columns=columns)
    return df

def main():
    print("=== Starting Statistical Hashing Comparison ===")
    print("Running Uniformity Tests (200 samples each)...")
    
    # 1. Uniformity
    chi_sha, dof_sha, crit_sha, pass_sha, counts_sha = run_uniformity_test("SHA-256", classical_sha256, num_categories=16)
    chi_md5, dof_md5, crit_md5, pass_md5, counts_md5 = run_uniformity_test("MD5", classical_md5, num_categories=16)
    chi_g3,  dof_g3,  crit_g3,  pass_g3,  counts_g3  = run_uniformity_test("Grover-3 Qubits", grover3_hex, num_categories=8)
    chi_g4,  dof_g4,  crit_g4,  pass_g4,  counts_g4  = run_uniformity_test("Grover-4 Qubits", grover4_hex, num_categories=16)
    chi_g8,  dof_g8,  crit_g8,  pass_g8,  counts_g8  = run_uniformity_test("Grover-8 Qubits", grover8_hex, num_categories=16)
    chi_gn4, dof_gn4, crit_gn4, pass_gn4, counts_gn4 = run_uniformity_test("GroverNL-4 Qubits", grover_nonlinear4_hex, num_categories=16)
    chi_gn8, dof_gn8, crit_gn8, pass_gn8, counts_gn8 = run_uniformity_test("GroverNL-8 Qubits", grover_nonlinear8_hex, num_categories=16)
    
    uni_sha = (chi_sha, dof_sha, crit_sha, pass_sha)
    uni_md5 = (chi_md5, dof_md5, crit_md5, pass_md5)
    uni_g3  = (chi_g3, dof_g3, crit_g3, pass_g3)
    uni_g4  = (chi_g4, dof_g4, crit_g4, pass_g4)
    uni_g8  = (chi_g8, dof_g8, crit_g8, pass_g8)
    uni_gn4 = (chi_gn4, dof_gn4, crit_gn4, pass_gn4)
    uni_gn8 = (chi_gn8, dof_gn8, crit_gn8, pass_gn8)
    
    print("Running Hamming Distance Tests (30 samples per message length)...")
    
    # 2. Hamming
    ham_sha = run_hamming_test(classical_sha256)
    ham_md5 = run_hamming_test(classical_md5)
    ham_g3  = run_hamming_test(grover3_hex)
    ham_g4  = run_hamming_test(grover4_hex)
    ham_g8  = run_hamming_test(grover8_hex)
    ham_gn4 = run_hamming_test(grover_nonlinear4_hex)
    ham_gn8 = run_hamming_test(grover_nonlinear8_hex)
    
    # Generate plots
    print("Generating Uniformity Bar Graphs...")
    plot_uniformity(counts_sha, "Distribution of Hexadecimal Characters in SHA-256 Hash Output", "classical_sha256_hash_uniformity_distribution.svg")
    plot_uniformity(counts_md5, "Distribution of Hexadecimal Characters in MD5 Hash Output", "classical_md5_hash_uniformity_distribution.svg")
    plot_uniformity(counts_g8, "Distribution of Hexadecimal Characters in Grover-8 Hash Output", "quantum_uniformity.png")
    plot_uniformity(counts_gn4, "Distribution of Hexadecimal Characters in GroverNL-4 Hash Output", "grover_nonlinear4_hash_uniformity_distribution.svg")
    plot_uniformity(counts_gn8, "Distribution of Hexadecimal Characters in GroverNL-8 Hash Output", "grover_nonlinear8_hash_uniformity_distribution.svg")

    print("Generating Hamming Distance Heatmaps...")
    print("Generating SHA-256 Hamming distance cache...")
    df_sha = generate_classical_hamming_cache(classical_sha256)
    plt.figure(figsize=(10, 6))
    sns.heatmap(df_sha.T, annot=False, cmap='viridis')
    plt.title("Hamming Distance for sha256")
    plt.tight_layout()
    save_plot("classical_sha256_hamming_distance.svg")
    plt.close()

    print("Generating MD5 Hamming distance cache...")
    df_md5 = generate_classical_hamming_cache(classical_md5)
    plt.figure(figsize=(10, 6))
    sns.heatmap(df_md5.T, annot=False, cmap='viridis')
    plt.title("Hamming Distance for md5")
    plt.tight_layout()
    save_plot("classical_md5_hamming_distance.svg")
    plt.close()

    print("Generating Grover-8 Hamming distance cache...")
    df_g8 = generate_classical_hamming_cache(grover8_hex, max_length=24, num_flips=5, samples=2)
    plt.figure(figsize=(10, 6))
    sns.heatmap(df_g8.T, annot=False, cmap='viridis')
    plt.title("Hamming Distance for Grover-8")
    plt.xlabel("Message Bit Length")
    plt.ylabel("Number of Bit Flips")
    plt.tight_layout()
    save_plot("grover8_hamming_distance.svg")
    plt.close()

    print("Generating GroverNL-8 Hamming distance cache...")
    df_gn8 = generate_classical_hamming_cache(grover_nonlinear8_hex, max_length=24, num_flips=5, samples=2)
    plt.figure(figsize=(10, 6))
    sns.heatmap(df_gn8.T, annot=False, cmap='viridis')
    plt.title("Hamming Distance for GroverNL-8")
    plt.xlabel("Message Bit Length")
    plt.ylabel("Number of Bit Flips")
    plt.tight_layout()
    save_plot("grover_nonlinear8_hamming_distance.svg")
    plt.close()

    quantum_csv = "/home/isati/dev/uni/projects/code/hashing/hamming2.csv"
    if os.path.exists(quantum_csv):
        print(f"Loading precomputed quantum Hamming distance from {quantum_csv}...")
        df_quantum = pd.read_csv(quantum_csv)
        if 'Unnamed: 0' in df_quantum.columns:
            df_quantum = df_quantum.drop(columns=['Unnamed: 0'])
        elif '' in df_quantum.columns:
            df_quantum = df_quantum.drop(columns=[''])
            
        plt.figure(figsize=(10, 6))
        sns.heatmap(df_quantum.T, annot=False, cmap='viridis')
        plt.title("Heatmap of hamming distance between number of bit flips and hash length")
        plt.tight_layout()
        save_plot("quantum_hamming_distance.svg")
        plt.close()
    else:
        print(f"Warning: Precomputed quantum Hamming distance file not found at {quantum_csv}. Skipping quantum heatmap.")

    # Print results report
    report = []
    report.append("# Hashing Comparison Report")
    report.append("Comparing Grover's Hashing (3, 4, 8 qubits) to SHA-256 and MD5 for uniformity (Chi-Squared Test) and Hamming distance.\n")
    
    report.append("## 1. Uniformity Test Results")
    report.append("| Algorithm | Chi2 Statistic | DoF | Critical Value (alpha=0.05) | Passed Uniformity? |")
    report.append("|-----------|----------------|-----|-----------------------------|--------------------|")
    
    for name, res in [("SHA-256", uni_sha), ("MD5", uni_md5), ("Grover (3 Qubits)", uni_g3), ("Grover (4 Qubits)", uni_g4), ("Grover (8 Qubits)", uni_g8), ("GroverNL (4 Qubits)", uni_gn4), ("GroverNL (8 Qubits)", uni_gn8)]:
        chi2, dof, crit, passed = res
        passed_str = "Yes" if passed else "No"
        report.append(f"| {name:<17} | {chi2:>14.3f} | {dof:>3} | {crit:>27.3f} | {passed_str:<18} |")
        
    report.append("\n## 2. Average Normalized Hamming Distance (Target: 0.50)")
    report.append("| Algorithm | 1-bit Flip | 2-bit Flips | 3-bit Flips | 4-bit Flips | 5-bit Flips |")
    report.append("|-----------|------------|-------------|-------------|-------------|-------------|")
    
    for name, hams in [("SHA-256", ham_sha), ("MD5", ham_md5), ("Grover (3 Qubits)", ham_g3), ("Grover (4 Qubits)", ham_g4), ("Grover (8 Qubits)", ham_g8), ("GroverNL (4 Qubits)", ham_gn4), ("GroverNL (8 Qubits)", ham_gn8)]:
        hams_str = " | ".join(f"{h:.3f}" for h in hams)
        report.append(f"| {name:<17} | {hams_str} |")
    report.append("\n## 3. Visualization Plots")
    report.append("### 3.1 Uniformity Distributions")
    report.append("![SHA-256 Uniformity](classical_sha256_hash_uniformity_distribution.svg)")
    report.append("![MD5 Uniformity](classical_md5_hash_uniformity_distribution.svg)")
    report.append("![Quantum Uniformity](quantum_uniformity.png)")
    report.append("![GroverNL-4 Uniformity](grover_nonlinear4_hash_uniformity_distribution.svg)")
    report.append("![GroverNL-8 Uniformity](grover_nonlinear8_hash_uniformity_distribution.svg)")
    
    report.append("\n### 3.2 Hamming Distance Heatmaps")
    report.append("![SHA-256 Hamming Distance](classical_sha256_hamming_distance.svg)")
    report.append("![MD5 Hamming Distance](classical_md5_hamming_distance.svg)")
    report.append("![Quantum Hamming Distance](quantum_hamming_distance.svg)")
    report.append("![Grover-8 Hamming Distance](grover8_hamming_distance.svg)")
    report.append("![GroverNL-8 Hamming Distance](grover_nonlinear8_hamming_distance.svg)")

    report_content = "\n".join(report)
    print("\n" + report_content)
    
    with open("benchmarks/comparison_report.md", "w") as f:
        f.write(report_content)
    print("\nSuccessfully saved report to benchmarks/comparison_report.md")

if __name__ == "__main__":
    main()
