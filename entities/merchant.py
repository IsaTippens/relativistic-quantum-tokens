import time
import logging

logger = logging.getLogger(__name__)

class Merchant:
    """
    The Merchant (Charlie) receives the token and routes it to the Bank.
    """
    def __init__(self, name: str, location_geohash: str):
        self.name = name
        self.location = location_geohash

    def get_location(self) -> str:
        return self.location

    def get_timestamp(self) -> str:
        # Returns current time as an ISO string or just string timestamp
        return str(time.time())

    def receive_token_and_settle(self, token_payload: dict, bank) -> bool:
        """
        Receives the token payload from Alice and immediately settles with the Bank.
        """
        logger.info(f"Merchant ({self.name}): Received token payload from Alice.")
        logger.info(f"Merchant ({self.name}): Routing transaction to Bank for settlement...")
        
        # Call Bank to verify
        is_valid = bank.verify_settlement(token_payload)
        
        if is_valid:
            logger.info(f"Merchant ({self.name}): Transaction settled successfully.")
        else:
            logger.warning(f"Merchant ({self.name}): Transaction failed settlement.")
            
        return is_valid
