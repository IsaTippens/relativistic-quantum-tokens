import logging

import numpy as np
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, thermal_relaxation_error

logger = logging.getLogger(__name__)

# Measured on ibm_fez, run ibmq_20260908T220749Z (see results/.../qcs/):
#   T1  117.3 us   mean over 16 probe qubits
#   T2  100.0 us   device median
#   idle phase   -0.1094 rad/us on the pair used for the sync experiment
# These are the defaults so that a simulated idle window decoheres by roughly
# the amount the real device does, instead of being a free lunch.
MEASURED_T1_US = 117.3
MEASURED_T2_US = 100.0
MEASURED_IDLE_PHASE_RAD_PER_US = -0.1094

# Residual clock offset per stage, as a fraction of T1. Matches
# experiments/ibm/exp_qcs.py so the simulation and the hardware run describe
# the same three stages.
SYNC_STAGES = {"initial_drift": 1.0, "adjusting": 0.25, "synced": 0.0}


class TimeSyncSimulator:
    """
    Simulates the Quantum Time Synchronisation protocol.
    Prepares a Bell state, applies the relative phase corresponding to a time
    offset, optionally idles Bob's qubit for that offset using a delay gate,
    and measures the correlation.

    Two independent limits on the correlation are modelled:
      * `max_correlation` caps it via a depolarizing error on the entangling
        gate, standing in for gate infidelity;
      * `t1_us` / `t2_us` drive a thermal relaxation error attached to the
        delay instruction, so a longer clock offset costs real coherence.
    """
    def __init__(self, omega: float = 1.0, max_correlation: float = 1.0,
                 t1_us: float = MEASURED_T1_US, t2_us: float = MEASURED_T2_US,
                 idle_phase_rad_per_us: float = 0.0):
        self.omega = omega
        self.max_correlation = max_correlation
        self.t1_us = t1_us
        self.t2_us = t2_us
        self.idle_phase_rad_per_us = idle_phase_rad_per_us

        self.noise_model = NoiseModel(basis_gates=["cx", "h", "rz", "id", "delay"])

        # For a 2-qubit depolarizing error p, the correlation reduces by a
        # factor of (1-p), so (1-p) = max_correlation -> p = 1 - max_correlation
        p = 1.0 - max_correlation
        if p > 0:
            self.noise_model.add_all_qubit_quantum_error(depolarizing_error(p, 2), ["cx"])

        self.simulator = AerSimulator(noise_model=self.noise_model)

    def _delay_noise_model(self, delay_us: float) -> NoiseModel:
        """Noise model whose delay instruction relaxes for `delay_us`."""
        model = NoiseModel(basis_gates=["cx", "h", "rz", "id", "delay"])
        p = 1.0 - self.max_correlation
        if p > 0:
            model.add_all_qubit_quantum_error(depolarizing_error(p, 2), ["cx"])
        if delay_us > 0:
            t1_ns, t2_ns = self.t1_us * 1e3, self.t2_us * 1e3
            model.add_all_qubit_quantum_error(
                thermal_relaxation_error(t1_ns, min(t2_ns, 2 * t1_ns), delay_us * 1e3),
                ["delay"])
        return model

    def build_circuit(self, dt: float, delay_us: float = 0.0,
                      scan_phase: float = 0.0) -> QuantumCircuit:
        """Bell pair, Bob's offset as phase (and optionally idle time), X-basis."""
        qc = QuantumCircuit(2, 2)
        qc.h(0)
        qc.cx(0, 1)

        if delay_us > 0:
            qc.delay(delay_us, 1, "us")

        # A relative time offset translates to a relative phase shift, plus the
        # parasitic phase a real qubit picks up while idling.
        phase = self.omega * dt + self.idle_phase_rad_per_us * delay_us
        qc.rz(phase + scan_phase, 1)

        qc.h(0)
        qc.h(1)
        qc.measure([0, 1], [0, 1])
        return qc

    def simulate_measurement(self, t_a: float, t_b: float, shots: int = 1024,
                             sampler=None, delay_us: float = 0.0,
                             scan_phase: float = 0.0) -> float:
        """
        Simulate Alice measuring at t_a and Bob measuring at t_b.
        Returns the correlation between their measurements [-1.0, 1.0].
        `delay_us` idles Bob's qubit for that many microseconds and is opt-in:
        callers that treat t_a/t_b as abstract phase units (the original
        behaviour) get the pure phase model with no decoherence from idling.
        If sampler is provided, it dispatches the circuit to IBM hardware.
        """
        dt = t_a - t_b
        idle_us = delay_us
        qc = self.build_circuit(dt, idle_us, scan_phase)

        if sampler:
            # Hardware / Cloud Execution using SamplerV2
            job = sampler.run([qc])
            result = job.result()
            pub_result = result[0]
            counts = pub_result.data.c.get_counts()
            shots = sum(counts.values())
        else:
            # Local Simulation
            from qiskit import transpile
            sim = AerSimulator(noise_model=self._delay_noise_model(idle_us))
            t_qc = transpile(qc, backend=sim)
            job = sim.run(t_qc, shots=shots)
            counts = job.result().get_counts()

        # Calculate correlation
        same = counts.get('00', 0) + counts.get('11', 0)
        diff = counts.get('01', 0) + counts.get('10', 0)

        correlation = (same - diff) / shots
        return correlation

    def three_stage_sync(self, t1_us: float | None = None, shots: int = 1024,
                         sampler=None, scan_phases: int = 8) -> dict:
        """Run the three synchronisation stages and return each correlation.

        Stage residual offsets are fractions of the qubit relaxation time, so
        the idle windows stay "within reason" of how long a qubit actually
        survives: 1.0*T1 uncorrected, 0.25*T1 part-corrected, 0 synchronised.
        `omega` is interpreted in rad/us here, matching the hardware runner.
        """
        t1 = self.t1_us if t1_us is None else t1_us
        phases = [2 * np.pi * k / scan_phases for k in range(scan_phases)]
        stages = {}
        for stage, factor in SYNC_STAGES.items():
            dt = factor * t1
            points = [
                {"scan_phase": phase,
                 "correlation": self.simulate_measurement(
                     dt, 0.0, shots=shots, sampler=sampler,
                     delay_us=dt, scan_phase=phase)}
                for phase in phases
            ]
            corr = np.array([p["correlation"] for p in points])
            design = np.stack([np.cos(phases), -np.sin(phases)], axis=1)
            (c, s), *_ = np.linalg.lstsq(design, corr, rcond=None)
            stages[stage] = {
                "dt_us": dt,
                "applied_phase_rad": self.omega * dt,
                "correlation_at_zero_phase": points[0]["correlation"],
                "visibility": float(np.hypot(c, s)),
                "phase_offset_rad": float(np.arctan2(s, c)),
                "points": points,
            }
        return {
            "t1_us": t1,
            "omega_rad_per_us": self.omega,
            "idle_phase_rad_per_us": self.idle_phase_rad_per_us,
            "shots": shots,
            "stages": stages,
        }
