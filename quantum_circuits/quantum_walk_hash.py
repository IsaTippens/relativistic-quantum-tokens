import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime import SamplerV2
import hashlib

class QuantumWalkHash:
    """
    Implements a 1D Quantum Random Walk acting as a hash function.
    Output is a deterministic 4-bit hash based on the quantum measurement.
    """
    def __init__(self):
        # Build the controlled shift operators for the quantum walk
        # 4 position qubits = 16 states
        self.num_pos_qubits = 4
        
        inc_matrix = np.zeros((16, 16))
        for i in range(16):
            inc_matrix[(i + 1) % 16, i] = 1
            
        dec_matrix = np.zeros((16, 16))
        for i in range(16):
            dec_matrix[(i - 1) % 16, i] = 1
            
        inc_gate = UnitaryGate(inc_matrix, label="Inc")
        dec_gate = UnitaryGate(dec_matrix, label="Dec")
        
        self.c_inc = inc_gate.control(1, ctrl_state=1)
        self.c_dec = dec_gate.control(1, ctrl_state=0)

    def _string_to_binary(self, input_str: str) -> str:
        """
        Converts the input string to a binary string using SHA-256 to ensure
        a fixed, randomized distribution of bits, then taking the first 64 bits 
        for performance in the circuit simulation.
        """
        # Hash to bytes then to binary string
        hash_bytes = hashlib.sha256(input_str.encode('utf-8')).digest()
        bin_str = bin(int.from_bytes(hash_bytes, 'big'))[2:].zfill(256)
        return bin_str[:64] # Limit to 64 steps for circuit depth

    def build_circuit(self, input_str: str) -> QuantumCircuit:
        """
        Builds the quantum walk circuit based on the input string.
        """
        bin_str = self._string_to_binary(input_str)
        
        # Qubits: 0=Coin, 1..4=Position
        qc = QuantumCircuit(5, 4)
        
        # Initialize position to a superposition or just leave at 0
        # Let's start with a Hadamard on coin
        qc.h(0)
        
        for bit in bin_str:
            # Rotate coin based on the classical bit
            if bit == '1':
                qc.rx(np.pi / 2, 0)
            else:
                qc.ry(np.pi / 2, 0)
                
            # Conditional Shift
            qc.append(self.c_inc, [0, 1, 2, 3, 4])
            qc.append(self.c_dec, [0, 1, 2, 3, 4])
            
        # Measure the 4 position qubits
        qc.measure([1, 2, 3, 4], [0, 1, 2, 3])
        return qc

    def compute_hash(self, input_str: str, sampler=None) -> str:
        """
        Executes the circuit and returns the 4-bit hash (the most probable measurement).
        If sampler is provided (SamplerV2 from IBM), it will run on cloud/local primitive.
        Otherwise it uses AerSimulator.
        """
        qc = self.build_circuit(input_str)
        
        if sampler:
            # Using SamplerV2
            job = sampler.run([qc])
            result = job.result()
            # Get the pub result (primitive unified block)
            pub_result = result[0]
            # Get counts from the bit array
            counts = pub_result.data.c.get_counts()
        else:
            from qiskit import transpile
            # Fallback to standard AerSimulator execute
            sim = AerSimulator()
            t_qc = transpile(qc, backend=sim)
            job = sim.run(t_qc, shots=1024, seed_simulator=42)
            counts = job.result().get_counts()
            
        # Deterministic: pick the most frequently measured state
        best_hash = max(counts, key=counts.get)
        return best_hash
