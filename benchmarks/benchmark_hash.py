import time
import logging
import argparse
from quantum_circuits import QuantumWalkHash, FullQuantumHash, SimpleXORHash, XORWalkHash, GroverHash, GroverNonLinearHash
from utils.ibm_connector import get_ibm_sampler

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )

def run_benchmarks(payloads, num_runs=3):
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("=== Quantum Hash Benchmark ===")
    
    hash_algorithms = {
        "QuantumWalk": QuantumWalkHash(),
        "FullQuantum": FullQuantumHash(),
        "SimpleXOR": SimpleXORHash(),
        "XORWalk": XORWalkHash(),
        "Grover": GroverHash(),
        "GroverNonLinear": GroverNonLinearHash()
    }
    
    # Initialize samplers
    logger.info("Initializing Local AerSimulator...")
    local_sampler = None # None uses AerSimulator fallback
    
    logger.info("Initializing IBM Cloud SamplerV2...")
    cloud_sampler = get_ibm_sampler(use_cloud=True)
    
    if not cloud_sampler:
        logger.warning("Could not initialize IBM Cloud Sampler. Are credentials saved? Skipping cloud benchmarks.")
    
    print("\n| Algorithm    | Payload | Local Time (s) | Local Hash | Cloud Time (s) | Cloud Hash |")
    print("|--------------|---------|----------------|------------|----------------|------------|")
    
    for name, q_hash in hash_algorithms.items():
        for payload in payloads:
            # 1. Local Benchmark
            start_local = time.time()
            local_result = q_hash.compute_hash(payload, sampler=local_sampler)
            end_local = time.time()
            local_duration = end_local - start_local
            
            # 2. Cloud Benchmark
            cloud_duration_str = "N/A"
            cloud_result = "N/A"
            if cloud_sampler:
                start_cloud = time.time()
                try:
                    cloud_result = q_hash.compute_hash(payload, sampler=cloud_sampler)
                    end_cloud = time.time()
                    cloud_duration_str = f"{(end_cloud - start_cloud):.2f}"
                except Exception as e:
                    cloud_duration_str = "Error"
                    cloud_result = "Error"
            
            # Format hash for display (truncate if too long)
            disp_local = local_result[:10] + "..." if len(local_result) > 10 else local_result.ljust(10)
            disp_cloud = cloud_result[:10] + "..." if len(cloud_result) > 10 else cloud_result.ljust(10)
            
            print(f"| {name.ljust(12)} | {payload[:7]}... | {local_duration:.2f}           | {disp_local} | {cloud_duration_str}           | {disp_cloud} |")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Quantum Walk Hash")
    parser.add_argument("--payloads", type=int, default=3, help="Number of random payloads to benchmark")
    args = parser.parse_args()
    
    import uuid
    test_payloads = [str(uuid.uuid4()) for _ in range(args.payloads)]
    run_benchmarks(test_payloads)
