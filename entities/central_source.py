import logging
from quantum_circuits.time_sync_simulator import TimeSyncSimulator

logger = logging.getLogger(__name__)

class CentralSource:
    """
    Coordinates the scheduling of measurements and evaluates outcomes.
    """
    def __init__(self, omega: float = 1.0):
        self.simulator = TimeSyncSimulator(omega=omega, max_correlation=0.75)
        self.omega = omega

    def schedule_measurements(self, node_a, node_b, schedules: list[float], b_shifts: list[float]) -> list[float]:
        """
        Takes a list of true times to schedule measurements.
        b_shifts contains intentional measurement shifts applied by node_b.
        Returns the correlations for each scheduled time.
        """
        correlations = []
        for t, shift in zip(schedules, b_shifts):
            t_a = node_a.get_local_time(t)
            t_b = node_b.get_local_time(t, intentional_shift=shift)
            
            corr = self.simulator.simulate_measurement(t_a, t_b)
            correlations.append(corr)
            logger.debug(f"Source: Scheduled T={t} | {node_a.name} time: {t_a:.2f}, {node_b.name} time: {t_b:.2f} (shift: {shift:+.2f}) | Correlation: {corr:.4f}")
            
        return correlations
