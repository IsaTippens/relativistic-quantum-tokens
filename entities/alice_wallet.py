import logging
from quantum_circuits.quantum_walk_hash import QuantumWalkHash

logger = logging.getLogger(__name__)

class AliceWallet:
    """
    Alice's Wallet holds her shared secret and handles token generation to spend at a merchant.
    """
    def __init__(self, sampler=None):
        self.shared_secret = None
        self.serial_number = None
        self.sampler = sampler
        self.quantum_hash = QuantumWalkHash()

    def set_shared_secret(self, secret: str):
        self.shared_secret = secret
        logger.info("Alice: Shared secret received from BB84 exchange.")

    def receive_serial_number(self, serial: str):
        self.serial_number = serial
        logger.info("Alice: Received Serial Number from Bank.")

    def spend_at_merchant(self, merchant) -> dict:
        """
        Alice interacts with the Merchant (Charlie) to get Location and Timestamp,
        then computes the Quantum Hash and hands over the token.
        """
        logger.info(f"Alice: Attempting to spend token at Merchant ({merchant.name})...")
        
        location = merchant.get_location()
        timestamp = merchant.get_timestamp()
        
        logger.info(f"Alice: Received merchant details - Loc: {location}, Time: {timestamp}")
        
        if not self.shared_secret or not self.serial_number:
            raise ValueError("Alice does not have a valid token to spend.")

        # Concatenate classical string
        data_to_hash = f"{self.shared_secret}{self.serial_number}{location}{timestamp}"
        
        logger.info("Alice: Computing Quantum Hash for the transaction...")
        token_hash = self.quantum_hash.compute_hash(data_to_hash, self.sampler)
        
        logger.info(f"Alice: Generated token Hash: {token_hash}")
        
        # Payload given to Charlie
        payload = {
            "serial_number": self.serial_number,
            "hash": token_hash,
            "location": location,
            "timestamp": timestamp
        }
        
        return payload
