import logging
from quantum_circuits.quantum_walk_hash import QuantumWalkHash
from quantum_circuits.superdense_simulator import SuperdenseSimulator, encode_payload, decode_payload

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
        self.channel = SuperdenseSimulator()

    def set_shared_secret(self, secret: str):
        self.shared_secret = secret
        logger.info("Alice: Shared secret received from BB84 exchange.")

    def receive_serial_number(self, transmission: str) -> str:
        """Decodes the superdense-coded issuance message from the Bank."""
        self.serial_number = decode_payload(transmission)["serial_number"]
        logger.info("Alice: Received Serial Number from Bank over the superdense channel.")
        return self.serial_number

    def spend_at_merchant(self, merchant) -> str:
        """
        Alice reads the Merchant's location and timestamp off the
        superdense-coded channel, computes the Quantum Hash, and hands the
        token back as a superdense transmission.
        """
        logger.info(f"Alice: Attempting to spend token at Merchant ({merchant.name})...")

        quote = decode_payload(merchant.send_quote())
        location = quote["location"]
        timestamp = quote["timestamp"]
        
        logger.info(f"Alice: Received merchant details - Loc: {location}, Time: {timestamp}")
        
        if not self.shared_secret or not self.serial_number:
            raise ValueError("Alice does not have a valid token to spend.")

        # Concatenate classical string
        data_to_hash = f"{self.shared_secret}{self.serial_number}{location}{timestamp}"
        
        logger.info("Alice: Computing Quantum Hash for the transaction...")
        token_hash = self.quantum_hash.compute_hash(data_to_hash, self.sampler)
        
        logger.info(f"Alice: Generated token Hash: {token_hash}")
        
        # Payload handed to Charlie over the superdense-coded channel
        payload = {
            "serial_number": self.serial_number,
            "hash": token_hash,
            "location": location,
            "timestamp": timestamp
        }

        return self.channel.transmit_bits(encode_payload(payload))
