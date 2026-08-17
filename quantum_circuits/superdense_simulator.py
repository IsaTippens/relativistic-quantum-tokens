import json
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator


def encode_payload(payload: dict) -> str:
    """Serializes a classical payload to a bitstring for quantum transmission."""
    raw = json.dumps(payload, sort_keys=True).encode('utf-8')
    return ''.join(f'{byte:08b}' for byte in raw)


def decode_payload(bits: str) -> dict:
    """Deserializes a bitstring received over the quantum channel back to a payload."""
    raw = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
    return json.loads(raw.decode('utf-8'))


class SuperdenseSimulator:
    """
    Simulates superdense coding: two classical bits are transmitted per
    physical qubit by exploiting pre-shared Bell pairs |Phi+> between
    sender and receiver.

    Encoding convention (matches thesis_figures/superdense.png):
        bit pair (b0, b1) -> apply X if b1, then Z if b0, on the sender's half.
    Decoding applies CNOT(sender -> receiver) followed by H on the sender's
    qubit, projecting the pair back onto the computational basis.

    All gates are Clifford, so the stabilizer simulator handles arbitrarily
    large payloads in a single shot.
    """
    def __init__(self):
        self.simulator = AerSimulator(method='stabilizer')

    def _build_circuit(self, bits: str) -> QuantumCircuit:
        padded = bits if len(bits) % 2 == 0 else bits + '0'
        n_pairs = len(padded) // 2
        qc = QuantumCircuit(2 * n_pairs, 2 * n_pairs)

        for i in range(n_pairs):
            sender, receiver = 2 * i, 2 * i + 1

            # Distribute entangled pair
            qc.h(sender)
            qc.cx(sender, receiver)

            # Sender encodes two classical bits on their half
            if padded[2 * i + 1] == '1':
                qc.x(sender)
            if padded[2 * i] == '1':
                qc.z(sender)

            # Receiver decodes after receiving the sender's qubit
            qc.cx(sender, receiver)
            qc.h(sender)

            qc.measure(sender, 2 * i)
            qc.measure(receiver, 2 * i + 1)

        return qc

    def transmit_bits(self, bits: str) -> str:
        """
        Encodes a classical bitstring onto len(bits)/2 qubits and returns
        the bitstring the receiver decodes after measurement.
        """
        if not bits:
            return bits
        qc = self._build_circuit(bits)
        result = self.simulator.run(qc, shots=1).result()
        measured = list(result.get_counts().keys())[0]
        # Qiskit counts are little-endian: reverse so index i is classical bit i
        return measured[::-1][:len(bits)]

    def transmit_payload(self, payload: dict) -> dict:
        """Full round-trip: serialize, transmit over the quantum channel, decode."""
        return decode_payload(self.transmit_bits(encode_payload(payload)))
