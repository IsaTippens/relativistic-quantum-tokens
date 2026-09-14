import hashlib
import math
from qiskit import AncillaRegister, QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit_aer import AerSimulator

from quantum_circuits.non_linear_oracle import (
    feistel_ancilla_count,
    nonlinear_oracle,
    recommended_rounds,
)


def optimal_grover_iterations(hash_length: int) -> int:
    """Iterations that maximise the marked amplitude for one marked state.

    round(pi/4 * sqrt(2**n)): 2 for n=3, 3 for n=4, 13 for n=8. Below this the
    hash's argmax is sampling noise rather than a function of the message -
    at n=8 with the 2 iterations used in the thesis benchmarks the top outcome
    only carries ~0.095 probability and changes with the simulator seed, while
    at 13 iterations it carries ~0.99 and is stable. The default iteration
    counts are deliberately left at the shallower thesis values because the
    optimal count multiplies circuit depth by ~6.
    """
    return max(1, round(math.pi / 4 * math.sqrt(2 ** hash_length)))

class GroverHash:
    """
    Implements a streaming Grover-style quantum hash function.
    Based on the implementation in /home/isati/dev/uni/projects/code/hashing/grover.ipynb
    """
    def __init__(self, hash_length: int = 8, grover_iterations: int = 1, chunk_size: int = 8):
        self.hash_length = hash_length
        self.grover_iterations = grover_iterations
        self.chunk_size = chunk_size

    def _string_to_binary(self, input_str: str) -> str:
        """
        Converts the input string to a binary string.
        If the input already looks like a binary string, it uses it directly.
        Otherwise, it hashes the input string with SHA-256 and takes the first 16 bits
        to keep the number of blocks to 2, ensuring fast execution.
        """
        if all(c in '01' for c in input_str) and len(input_str) > 0:
            return input_str
        
        # Hash to bytes then to binary string
        hash_bytes = hashlib.sha256(input_str.encode('utf-8')).digest()
        bin_str = bin(int.from_bytes(hash_bytes, 'big'))[2:].zfill(256)
        return bin_str[:16]

    def build_circuit(self, input_str: str) -> QuantumCircuit:
        """
        Builds the Grover hashing circuit for the given input string.
        """
        bin_str = self._string_to_binary(input_str)
        n = self.hash_length
        
        qr = QuantumRegister(n, "q")
        cr = ClassicalRegister(n, "c")
        qc = QuantumCircuit(qr, cr)

        # Step 1: Initialize in uniform superposition
        for q in range(n):
            qc.h(qr[q])

        # Step 2: Process input in blocks
        for i in range(0, len(bin_str), self.chunk_size):
            block = bin_str[i:i+self.chunk_size].ljust(self.chunk_size, '0')
            target_index = int(block, 2) % (2 ** n)

            for _ in range(self.grover_iterations):
                # --- Oracle: mark target_index ---
                for j in range(n):
                    if ((target_index >> j) & 1) == 0:
                        qc.x(qr[j])
                
                qc.h(qr[n-1])
                qc.mcx(list(range(n-1)), qr[n-1])
                qc.h(qr[n-1])
                
                for j in range(n):
                    if ((target_index >> j) & 1) == 0:
                        qc.x(qr[j])

                # --- Diffusion ---
                for j in range(n):
                    qc.h(qr[j])
                    qc.x(qr[j])
                
                qc.h(qr[n-1])
                qc.mcx(list(range(n-1)), qr[n-1])
                qc.h(qr[n-1])
                
                for j in range(n):
                    qc.x(qr[j])
                    qc.h(qr[j])

        # Step 3: Measure
        qc.measure(qr, cr)
        return qc

    def compute_hash(self, input_str: str, sampler=None, shots: int = 1024) -> str:
        """
        Executes the circuit and returns the most likely measurement as a binary string.
        """
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
        return best_hash

class GroverNonLinearHash(GroverHash):
    """Grover hash whose oracle marks f(x) for a Feistel permutation f.

    The oracle contract (verified in tests/test_feistel_oracle.py) is
    ``U|x>|0> = (-1)^[f(x) == block] |x>|0>``: the Feistel network is computed
    onto the search register, the phase is applied on the block target, and the
    network is inverted so the ancillas come back clean and the diffusion
    operator sees the ``x`` basis. Diffusion itself is unchanged from
    :class:`GroverHash`.
    """

    def __init__(self, hash_length: int = 8, grover_iterations: int = 2,
                 chunk_size: int = 8, rounds: int | None = None):
        if hash_length < 3:
            raise ValueError("hash_length must be at least 3 for a Feistel network")
        super().__init__(hash_length, grover_iterations, chunk_size)
        self.rounds = recommended_rounds(hash_length) if rounds is None else rounds

    @property
    def num_ancillas(self) -> int:
        return feistel_ancilla_count(self.hash_length)

    def build_circuit(self, input_str: str) -> QuantumCircuit:
        bin_str = self._string_to_binary(input_str)
        n = self.hash_length
        n_anc = self.num_ancillas

        qr = QuantumRegister(n, "q")
        anc = AncillaRegister(n_anc, "fa")
        cr = ClassicalRegister(n, "c")
        qc = QuantumCircuit(qr, anc, cr)

        # Step 1: Initialize in uniform superposition
        for q in range(n):
            qc.h(qr[q])

        # Step 2: Process input in blocks
        oracles: dict[int, QuantumCircuit] = {}
        for i in range(0, len(bin_str), self.chunk_size):
            block = bin_str[i:i + self.chunk_size].ljust(self.chunk_size, '0')
            target_index = int(block, 2) % (2 ** n)
            if target_index not in oracles:
                oracles[target_index] = nonlinear_oracle(n, target_index, rounds=self.rounds)
            oracle_circuit = oracles[target_index]

            for _ in range(self.grover_iterations):
                # --- Oracle: phase-flip every x whose Feistel image is the block ---
                qc.compose(oracle_circuit, qubits=list(qr) + list(anc), inplace=True)

                # --- Diffusion (identical to the linear GroverHash) ---
                for j in range(n):
                    qc.h(qr[j])
                    qc.x(qr[j])

                qc.h(qr[n - 1])
                qc.mcx(list(qr[:n - 1]), qr[n - 1])
                qc.h(qr[n - 1])

                for j in range(n):
                    qc.x(qr[j])
                    qc.h(qr[j])

        # Step 3: Measure the main register (qr) into the classical register (cr)
        qc.measure(qr, cr)
        return qc
