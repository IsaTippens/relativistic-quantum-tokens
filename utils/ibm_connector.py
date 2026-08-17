import logging
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

logger = logging.getLogger(__name__)

def get_ibm_sampler(backend_name: str = "ibm_brisbane", use_cloud: bool = False):
    """
    Returns a SamplerV2 for dispatching circuits.
    If use_cloud is True, loads saved IBM Quantum account and returns the sampler.
    Returns None if use_cloud is False, to signify local AerSimulation.
    """
    if not use_cloud:
        logger.info("Configured to use local AerSimulator.")
        return None
        
    try:
        logger.info("Initializing QiskitRuntimeService from saved account...")
        service = QiskitRuntimeService(channel="ibm_quantum")
        backend = service.backend(backend_name)
        sampler = SamplerV2(mode=backend)
        logger.info(f"Successfully connected to IBM backend: {backend.name}")
        return sampler
    except Exception as e:
        logger.error(f"Failed to initialize IBM Sampler: {e}")
        logger.info("Falling back to local simulation.")
        return None
