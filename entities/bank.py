import uuid
import logging
from quantum_circuits.bb84_simulator import BB84Simulator
from quantum_circuits.quantum_walk_hash import QuantumWalkHash

logger = logging.getLogger(__name__)

class Bank:
    """
    The Bank entity manages token issuance and settlement verification.
    """
    def __init__(self, sampler=None):
        # Database mapping Serial Number -> Shared Secret State
        self.ledger = {}
        self.sampler = sampler
        self.quantum_hash = QuantumWalkHash()

    def perform_bb84_exchange(self, alice) -> str:
        """
        Simulates BB84 with Alice to generate a shared secret.
        In reality, Alice and Bank would communicate over a quantum channel.
        """
        logger.info("Bank: Initiating BB84 key exchange with Alice...")
        simulator = BB84Simulator(num_bits=128)
        shared_secret = simulator.generate_shared_secret()
        logger.info(f"Bank: BB84 complete. Shared secret generated (length: {len(shared_secret)} bits).")
        
        # Set the secret for Alice too, to simulate the successful exchange
        alice.set_shared_secret(shared_secret)
        return shared_secret

    def issue_serial_number(self, shared_secret: str) -> str:
        """
        Generates a new Serial Number, stores it with the secret, and returns it.
        """
        serial_number = str(uuid.uuid4())
        self.ledger[serial_number] = shared_secret
        logger.info(f"Bank: Issued new Serial Number: {serial_number}")
        return serial_number

    def verify_settlement(self, payload: dict) -> bool:
        """
        Verifies the settlement payload from the merchant.
        """
        serial_number = payload.get("serial_number")
        provided_hash = payload.get("hash")
        location = payload.get("location")
        timestamp = payload.get("timestamp")

        logger.info(f"Bank: Received settlement request for Serial: {serial_number}")

        if serial_number not in self.ledger:
            logger.error("Bank: Serial number not found in ledger.")
            return False

        secret_state = self.ledger[serial_number]
        
        # Reconstruct the string
        data_to_hash = f"{secret_state}{serial_number}{location}{timestamp}"
        
        logger.info("Bank: Recomputing Quantum Hash...")
        expected_hash = self.quantum_hash.compute_hash(data_to_hash, self.sampler)
        
        logger.info(f"Bank: Expected Hash: {expected_hash}, Provided Hash: {provided_hash}")
        
        if expected_hash == provided_hash:
            logger.info("Bank: Settlement VERIFIED. Transaction successful.")
            return True
        else:
            logger.warning("Bank: Settlement REJECTED. Hash mismatch.")
            return False
