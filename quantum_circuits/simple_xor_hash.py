import qiskit
from qiskit_aer import AerSimulator
import hashlib

class SimpleXORHash:
    def __init__(self):
        pass

    def _string_to_binary(self, input_str: str) -> str:
        hash_bytes = hashlib.sha256(input_str.encode('utf-8')).digest()
        bin_str = bin(int.from_bytes(hash_bytes, 'big'))[2:].zfill(256)
        return bin_str[:16] # Limit to 16 bits to prevent CircuitTooWideForTarget

    def build_circuit(self, input_str: str) -> qiskit.QuantumCircuit:
        bin_str = self._string_to_binary(input_str)
        
        # We need pairs for parity, so ensure even length
        if len(bin_str) % 2 != 0:
            bin_str += '0'
            
        num_walk_qubits = len(bin_str)
        num_parity_qubits = num_walk_qubits // 2
        
        qc = qiskit.QuantumCircuit(num_walk_qubits + num_parity_qubits, num_parity_qubits)
        
        # Walk qubits based on bitstr
        for i, bit in enumerate(bin_str):
            if bit == "1":
                qc.x(i)
                
        # Apply parity
        for i in range(num_parity_qubits):
            parity_qubit_idx = num_walk_qubits + i
            walk_idx_1 = i * 2
            walk_idx_2 = i * 2 + 1
            
            qc.h(parity_qubit_idx)
            qc.cz(walk_idx_1, parity_qubit_idx)
            qc.cz(walk_idx_2, parity_qubit_idx)
            qc.h(parity_qubit_idx)
            
            qc.measure(parity_qubit_idx, i)
            
        return qc

    def compute_hash(self, input_str: str, sampler=None) -> str:
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
            job = sim.run(t_qc, shots=1024, seed_simulator=42)
            counts = job.result().get_counts()
            
        best_hash = max(counts, key=counts.get)
        
        # Convert to hex
        hex_string = hex(int(best_hash, 2))[2:].upper()
        return hex_string
