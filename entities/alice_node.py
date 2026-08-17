from quantum_circuits.grover_hash import GroverHash
from quantum_circuits.superdense_simulator import SuperdenseSimulator, encode_payload

class AliceNode:
    def __init__(self):
        self.shared_secret = None
        self.serial_number = None
        self.channel = SuperdenseSimulator()

    def program_token(self, target_geohash: str, expiration_timestamp: float, hash_length: int = 4) -> dict:
        if not self.shared_secret or not self.serial_number:
            raise ValueError("Node must undergo BB84 exchange first.")
            
        input_str = f"{self.shared_secret}{self.serial_number}{target_geohash}{expiration_timestamp}"
        aah_hash = GroverHash(hash_length=hash_length).compute_hash(input_str)
        
        return {
            "serial_number": self.serial_number,
            "target_geohash": target_geohash,
            "expiration_timestamp": expiration_timestamp,
            "hash": aah_hash
        }

    def send_token(self, payload: dict) -> str:
        """
        Transmits the token payload to Charlie via superdense coding:
        the classical bits are encoded onto half as many qubits drawn
        from pre-shared Bell pairs.
        """
        return self.channel.transmit_bits(encode_payload(payload))
