from quantum_circuits.superdense_simulator import SuperdenseSimulator, encode_payload, decode_payload

class CharlieNode:
    def __init__(self):
        self.channel = SuperdenseSimulator()

    async def receive_and_settle(self, transmission: str, current_time: float, current_geohash: str, bank_node, hash_length: int = 4):
        # Decode the qubits received from Alice (superdense coding)
        token_payload = decode_payload(transmission)

        # Appends classical state to payload and routes it to BankNode,
        # again over the superdense-coded quantum channel
        settlement_payload = dict(token_payload)
        settlement_payload['current_time'] = current_time
        settlement_payload['current_geohash'] = current_geohash
        bank_transmission = self.channel.transmit_bits(encode_payload(settlement_payload))
        return await bank_node.verify_settlement(bank_transmission, hash_length=hash_length)
