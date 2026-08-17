import numpy as np
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error
import logging

logger = logging.getLogger(__name__)

class TimeSyncSimulator:
    """
    Simulates the Quantum Time Synchronisation protocol.
    Prepares a Bell state, applies relative phase shift corresponding to time offset,
    and measures the correlation. Limits max correlation using depolarizing noise to mimic hardware.
    """
    def __init__(self, omega: float = 1.0, max_correlation: float = 1.0):
        self.omega = omega
        self.max_correlation = max_correlation
        
        # Add a noise model to cap the maximum correlation
        self.noise_model = NoiseModel()
        
        # For a 2-qubit depolarizing error p, the correlation reduces by a factor of (1-p)
        # So (1-p) = max_correlation -> p = 1 - max_correlation
        p = 1.0 - max_correlation
        if p > 0:
            error = depolarizing_error(p, 2)
            self.noise_model.add_all_qubit_quantum_error(error, ['cx'])
            
        self.simulator = AerSimulator(noise_model=self.noise_model)

    def simulate_measurement(self, t_a: float, t_b: float, shots: int = 1024, sampler=None) -> float:
        """
        Simulate Alice measuring at t_a and Bob measuring at t_b.
        Returns the correlation between their measurements [-1.0, 1.0].
        If sampler is provided, it dispatches the circuit to IBM hardware.
        """
        # Create Bell state |Phi+>
        qc = QuantumCircuit(2, 2)
        qc.h(0)
        qc.cx(0, 1)

        # Dephasing due to time offset
        # A relative time offset translates to a relative phase shift
        dt = t_a - t_b
        phase_shift = self.omega * dt
        
        # Apply the phase shift to one qubit
        qc.rz(phase_shift, 0)

        # Measure in X basis
        qc.h(0)
        qc.h(1)
        qc.measure([0, 1], [0, 1])

        if sampler:
            # Hardware / Cloud Execution using SamplerV2
            job = sampler.run([qc])
            result = job.result()
            pub_result = result[0]
            # Access the counts from the classical register (default is 'c')
            counts = pub_result.data.c.get_counts()
        else:
            # Local Simulation
            from qiskit import transpile
            t_qc = transpile(qc, backend=self.simulator)
            job = self.simulator.run(t_qc, shots=shots)
            counts = job.result().get_counts()

        # Calculate correlation
        same = counts.get('00', 0) + counts.get('11', 0)
        diff = counts.get('01', 0) + counts.get('10', 0)
        
        correlation = (same - diff) / shots
        return correlation
