import math

import qiskit
from qiskit_aer import AerSimulator
import hashlib

INPUT_BITS = 16
"""Input width fed to the walk register (keeps the circuit inside device limits)."""


class SimpleXORHash:
    """Parity-kickback hash: each output bit is the XOR of one contiguous input group.

    ``hash_length`` output bits are produced from ``INPUT_BITS`` input bits by
    splitting the input into ``hash_length`` contiguous groups of
    ``ceil(INPUT_BITS / hash_length)`` bits (the last group is short when the
    split is uneven). Each output bit is computed by phase kickback: an ancilla
    in |+> collects a CZ from every qubit of its group, so it lands in |-> iff
    that group's parity is odd.

    hash_length=8 reproduces the original adjacent-pair construction exactly.
    """

    def __init__(self, hash_length: int = 8):
        if not 1 <= hash_length <= INPUT_BITS:
            raise ValueError(f"hash_length must be in 1..{INPUT_BITS}")
        self.hash_length = hash_length

    def _string_to_binary(self, input_str: str) -> str:
        if all(c in '01' for c in input_str) and len(input_str) > 0:
            return input_str[:INPUT_BITS].ljust(INPUT_BITS, '0')
        hash_bytes = hashlib.sha256(input_str.encode('utf-8')).digest()
        bin_str = bin(int.from_bytes(hash_bytes, 'big'))[2:].zfill(256)
        return bin_str[:INPUT_BITS]

    def _groups(self) -> list[list[int]]:
        size = math.ceil(INPUT_BITS / self.hash_length)
        groups = []
        for g in range(self.hash_length):
            start = g * size
            groups.append(list(range(start, min(start + size, INPUT_BITS))))
        return groups

    def build_circuit(self, input_str: str) -> qiskit.QuantumCircuit:
        bin_str = self._string_to_binary(input_str)
        num_walk_qubits = INPUT_BITS
        num_parity_qubits = self.hash_length

        qc = qiskit.QuantumCircuit(num_walk_qubits + num_parity_qubits, num_parity_qubits)

        # Walk qubits carry the message bits
        for i, bit in enumerate(bin_str):
            if bit == "1":
                qc.x(i)

        # Parity extraction by phase kickback
        for i, group in enumerate(self._groups()):
            parity_qubit_idx = num_walk_qubits + i
            qc.h(parity_qubit_idx)
            for walk_idx in group:
                qc.cz(walk_idx, parity_qubit_idx)
            qc.h(parity_qubit_idx)
            qc.measure(parity_qubit_idx, i)

        return qc

    def compute_hash(self, input_str: str, sampler=None, shots: int = 1024) -> str:
        qc = self.build_circuit(input_str)

        if sampler:
            job = sampler.run([qc])
            result = job.result()
            pub_result = result[0]
            counts = pub_result.data.c.get_counts()
        else:
            from qiskit import transpile
            sim = AerSimulator()
            t_qc = transpile(qc, backend=sim)
            job = sim.run(t_qc, shots=shots, seed_simulator=42)
            counts = job.result().get_counts()

        best_hash = max(counts, key=counts.get)

        # Convert to hex
        hex_string = hex(int(best_hash, 2))[2:].upper()
        return hex_string
