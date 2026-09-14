import time
import logging
from quantum_circuits.superdense_simulator import SuperdenseSimulator, encode_payload, decode_payload

logger = logging.getLogger(__name__)

class Merchant:
    """
    The Merchant (Charlie) receives the token and routes it to the Bank.
    """
    def __init__(self, name: str, location_geohash: str):
        self.name = name
        self.location = location_geohash
        self.channel = SuperdenseSimulator()

    def send_quote(self) -> str:
        """
        Sends the merchant's location and current timestamp to Alice via
        superdense coding.
        """
        return self.channel.transmit_bits(encode_payload({
            "location": self.location,
            "timestamp": self.get_timestamp()
        }))

    def get_timestamp(self) -> str:
        # Returns current time as an ISO string or just string timestamp
        return str(time.time())

    def receive_token_and_settle(self, transmission: str, bank) -> bool:
        """
        Decodes the superdense-coded token from Alice and re-transmits the
        settlement bundle to the Bank over the same channel.
        """
        token_payload = decode_payload(transmission)
        logger.info(f"Merchant ({self.name}): Decoded token payload from Alice (serial: {token_payload.get('serial_number')}).")
        logger.info(f"Merchant ({self.name}): Routing transaction to Bank for settlement...")

        # The merchant -> bank leg rides the superdense-coded channel too
        is_valid = bank.verify_settlement(self.channel.transmit_bits(encode_payload(token_payload)))
        
        if is_valid:
            logger.info(f"Merchant ({self.name}): Transaction settled successfully.")
        else:
            logger.warning(f"Merchant ({self.name}): Transaction failed settlement.")
            
        return is_valid
