import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import argparse
import logging

# Add the project root to sys.path to resolve imports properly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from quantum_circuits.time_sync_simulator import TimeSyncSimulator
from utils.ibm_connector import get_ibm_sampler

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def run_tests():
    parser = argparse.ArgumentParser(description="Test and Graph Quantum Time Sync Correlation")
    parser.add_argument("--cloud", action="store_true", help="Run on IBM Quantum hardware in addition to simulation.")
    parser.add_argument("--output", type=str, default="benchmarks/correlation_graph.png", help="Output image filename.")
    args = parser.parse_args()

    omega = 1.0
    simulator = TimeSyncSimulator(omega=omega, max_correlation=1.0)
    
    # We will test time offsets (dt) from -2*pi to 2*pi
    dt_values = np.linspace(-2 * np.pi, 2 * np.pi, 30)
    
    sim_correlations = []
    logger.info("Running local simulation tests...")
    for dt in dt_values:
        # t_a = dt, t_b = 0 -> diff = dt
        corr = simulator.simulate_measurement(dt, 0.0)
        sim_correlations.append(corr)

    hw_correlations = []
    if args.cloud:
        logger.info("Initializing IBM hardware execution...")
        sampler = get_ibm_sampler(use_cloud=True)
        if sampler is not None:
            logger.info("Running hardware tests... This may take a while depending on queue times.")
            for dt in dt_values:
                # Note: real hardware may have limits on how many jobs you can submit.
                # In a real environment, you'd batch these into one job, but for MVP loop is fine.
                corr = simulator.simulate_measurement(dt, 0.0, sampler=sampler)
                hw_correlations.append(corr)
                logger.info(f"Hardware dt={dt:.2f}, corr={corr:.3f}")
        else:
            logger.warning("Failed to obtain IBM sampler. Skipping hardware plot.")
    
    # Analytical ideal curve (without depolarizing noise)
    ideal_correlations = np.cos(omega * dt_values)

    # Plotting
    plt.figure(figsize=(10, 6))
    plt.plot(dt_values, ideal_correlations, 'g--', label='Ideal Correlation (No Noise)')
    plt.plot(dt_values, sim_correlations, 'b-o', label='Simulated Correlation (Noiseless)')
    
    if len(hw_correlations) > 0:
        plt.plot(dt_values, hw_correlations, 'r-*', label='Hardware Correlation (IBM Cloud)')

    plt.title('Quantum Time Synchronisation: Correlation vs Time Offset')
    plt.xlabel(r'Time Offset $\Delta t$')
    plt.ylabel('Measurement Correlation')
    plt.axhline(0, color='black', linewidth=0.5)
    plt.axvline(0, color='black', linewidth=0.5)
    plt.grid(True, linestyle=':', alpha=0.7)
    plt.legend()
    
    output_path = os.path.abspath(args.output)
    plt.savefig(output_path)
    logger.info(f"Successfully saved graph to {output_path}")

if __name__ == "__main__":
    run_tests()
