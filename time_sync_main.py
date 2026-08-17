import logging
import argparse
from entities.central_source import CentralSource
from entities.time_node import TimeNode

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser(description="Run Quantum Time Synchronisation MVP.")
    parser.add_argument("--iterations", type=int, default=10, help="Number of sync intervals.")
    args = parser.parse_args()

    logger.info("=== Starting Quantum Time Synchronisation Protocol ===")
    
    # Omega determines the rate of dephasing (rads per time unit)
    omega = 1.0
    source = CentralSource(omega=omega)
    
    # Initialize Alice with 0 offset (reference), Bob with an unknown offset
    alice = TimeNode(name="Alice", initial_offset=0.0)
    bob = TimeNode(name="Bob", initial_offset=2.5) # Bob's clock is ahead by 2.5 units
    
    logger.info(f"Initial State -> Alice offset: {alice.clock_offset:.2f}, Bob offset: {bob.clock_offset:.2f}")

    # Synchronization Loop
    base_time = 0.0
    for i in range(args.iterations):
        logger.info(f"--- Sync Interval {i+1} ---")
        
        # Schedule 3 measurements
        # t1: normal
        # t2: Bob shifts by +delta
        # t3: Bob shifts by -delta
        schedules = [base_time, base_time + 10, base_time + 20]
        delta = 0.5
        b_shifts = [0.0, delta, -delta]
        
        correlations = source.schedule_measurements(alice, bob, schedules, b_shifts)
        c_base, c_plus, c_minus = correlations
        
        logger.info(f"Correlations | Base: {c_base:.3f}, +Shift: {c_plus:.3f}, -Shift: {c_minus:.3f}")
        
        # Logic to adjust Bob's clock based on correlations
        # The correlation curve is cos(omega * dt)
        # We want to maximize the correlation (dt -> 0).
        # We look at whether shifting +delta or -delta gave a better correlation.
        
        if max(c_base, c_plus, c_minus) >= 0.99 and abs(c_plus - c_minus) < 0.05:
            logger.info("Bob: Clocks appear to be synchronized. High correlation achieved.")
            # Still apply a tiny adjustment if one is strictly better, else 0
            pass

        # Calculate adjustment size based on derivative (c_plus - c_minus)
        # If c_plus > c_minus, dt is likely negative (Bob's time is behind Alice's time)
        # wait: if Bob's offset is +2.5, dt = t_a - t_b = -2.5.
        # shift +delta means t_b increases, so dt becomes -3.0. Correlation drops.
        # shift -delta means t_b decreases, so dt becomes -2.0. Correlation increases.
        # So c_minus > c_plus. To fix his offset, Bob should subtract from his clock.
        # If c_minus > c_plus, Bob should adjust by negative amount.
        
        # Simple proportional controller:
        # gradient = (c_plus - c_minus) / (2 * delta)
        # Because we want to maximize C, we step in direction of positive gradient.
        # However, we're shifting Bob's measurement time, which means adjusting the clock.
        
        gradient = c_plus - c_minus
        adjustment = gradient * 1.5  # scaling factor (learning rate)
        
        bob.adjust_clock(adjustment)
        
        base_time += 30

    logger.info("=== Protocol Complete ===")
    logger.info(f"Final State -> Alice offset: {alice.clock_offset:.4f}, Bob offset: {bob.clock_offset:.4f}")
    logger.info(f"Final true difference: {abs(alice.clock_offset - bob.clock_offset):.4f}")

if __name__ == "__main__":
    main()
