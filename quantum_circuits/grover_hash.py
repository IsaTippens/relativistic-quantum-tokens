import hashlib
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit_aer import AerSimulator

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
    def __init__(self, hash_length: int = 8, grover_iterations: int = 2, chunk_size: int = 8, rounds: int = 4):
        assert hash_length % 2 == 0, "hash_length must be even for GroverNonLinearHash"
        super().__init__(hash_length, grover_iterations, chunk_size)
        self.rounds = rounds

    def build_circuit(self, input_str: str) -> QuantumCircuit:
        bin_str = self._string_to_binary(input_str)
        n = self.hash_length
        n_half = n // 2
        
        from quantum_circuits.non_linear_oracle import nonlinear_oracle
        oracle_circuit = nonlinear_oracle(n, rounds=self.rounds)
        
        qr = QuantumRegister(n, "q")
        anc = QuantumRegister(n_half, "anc")
        temp = QuantumRegister(1, "temp")
        cr = ClassicalRegister(n, "c")
        qc = QuantumCircuit(qr, anc, temp, cr)

        # Step 1: Initialize in uniform superposition
        for q in range(n):
            qc.h(qr[q])

        # Step 2: Process input in blocks
        for i in range(0, len(bin_str), self.chunk_size):
            block = bin_str[i:i+self.chunk_size].ljust(self.chunk_size, '0')
            target_index = int(block, 2) % (2 ** n)

            for _ in range(self.grover_iterations):
                # --- XOR the target block index onto the main register qubits ---
                for j in range(n):
                    if (target_index >> j) & 1:
                        qc.x(qr[j])
                
                # --- Compose nonlinear_oracle onto main circuit ---
                qc = qc.compose(oracle_circuit, qubits=list(range(n + n_half + 1)))
                
                # --- XOR the target block index again onto the main register qubits ---
                for j in range(n):
                    if (target_index >> j) & 1:
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

        # Step 3: Measure the main register (qr) into the classical register (cr)
        qc.measure(qr, cr)
        return qc
