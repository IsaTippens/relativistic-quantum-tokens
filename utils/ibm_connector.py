"""SamplerV2 factory for the IBM Quantum cloud.

The account is the "qpus" instance (plan: open, region: us-east) reached with
the IBM_CLOUD_API_KEY in .env. The legacy `ibm_quantum` channel was retired by
IBM and removed in qiskit-ibm-runtime 0.4x, so the connection goes through
`ibm_quantum_platform`; experiments/ibm/common.py owns the account plumbing and
this module reuses it so both paths always agree on instance and backend.
"""
import logging

logger = logging.getLogger(__name__)


def get_ibm_sampler(backend_name: str | None = None, use_cloud: bool = False,
                    shots: int = 1024):
    """
    Returns a SamplerV2 for dispatching circuits.
    If use_cloud is True, connects to the IBM Quantum Platform and returns the
    sampler bound to `backend_name` (default: the freshest calibrated QPU that
    experiments/ibm/common.select_backend picks).
    Returns None if use_cloud is False, to signify local AerSimulation.
    """
    if not use_cloud:
        logger.info("Configured to use local AerSimulator.")
        return None

    try:
        from qiskit_ibm_runtime import SamplerV2

        from experiments.ibm.common import get_service, select_backend

        service = get_service()
        if backend_name:
            backend = service.backend(backend_name)
        else:
            backend, _ = select_backend()
        sampler = SamplerV2(mode=backend)
        sampler.options.default_shots = shots
        logger.info(f"Successfully connected to IBM backend: {backend.name}")
        return sampler
    except Exception as e:
        logger.error(f"Failed to initialize IBM Sampler: {e}")
        logger.info("Falling back to local simulation.")
        return None
