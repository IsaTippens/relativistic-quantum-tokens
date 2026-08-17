import qiskit
from qiskit_aer import AerSimulator
import hashlib
from qiskit import QuantumRegister, ClassicalRegister, QuantumCircuit

class XORWalkHash:
    def __init__(self):
        pass

    def _string_to_binary(self, input_str: str) -> str:
        hash_bytes = hashlib.sha256(input_str.encode('utf-8')).digest()
        bin_str = bin(int.from_bytes(hash_bytes, 'big'))[2:].zfill(256)
        return bin_str[:8] # Limit to 8 bits to match the 8 walk qubits in the original script

    def c_increment(self, qc: QuantumCircuit, qr: list, coin) -> QuantumCircuit:
        for i in range(len(qr) - 1):
            control_qubits = [coin] + [qr[j] for j in range(i+1, len(qr))]
            qc.mcx(control_qubits, qr[i])
        qc.cx(coin, qr[-1]) # Controlled LSB flip
        return qc

    def c_decrement(self, qc: QuantumCircuit, qr: list, coin) -> QuantumCircuit:
        qc.cx(coin, qr[-1]) # Un-flip the LSB first
        for i in reversed(range(len(qr) - 1)):
            control_qubits = [coin] + [qr[j] for j in range(i+1, len(qr))]
            qc.mcx(control_qubits, qr[i])
        return qc

    def build_circuit(self, input_str: str) -> QuantumCircuit:
        bin_str = self._string_to_binary(input_str)
        
        walk_qr = QuantumRegister(8, "walk")
        parity_qr = QuantumRegister(4, "parity")
        coin_qr = QuantumRegister(1, "coin")
        hash_cr = ClassicalRegister(4, "hash")

        qc = QuantumCircuit(walk_qr, parity_qr, coin_qr, hash_cr)

        walk_qubits = [walk_qr[i] for i in range(8)]
        coin = coin_qr[0]

        for bit in bin_str:
            # A. Coin Operator: Read in the bitstring
            if bit == "1":
                qc.x(coin)
                
            # B. C-Shift: If coin is |1>, perform increment
            self.c_increment(qc, walk_qubits, coin)
            
            # C. C-Shift: If coin is |0>, perform decrement
            qc.x(coin)
            self.c_decrement(qc, walk_qubits, coin)
            qc.x(coin)
            
            # D. Uncompute / Reset the coin for the next iteration step
            if bit == "1":
                qc.x(coin)

        # 3. Apply Parity checks
        for i in range(4):
            qc.h(parity_qr[i])
            qc.cz(walk_qr[i*2], parity_qr[i])
            qc.cz(walk_qr[i*2+1], parity_qr[i])
            qc.h(parity_qr[i])

            qc.measure(parity_qr[i], hash_cr[i])
            
        return qc

    def compute_hash(self, input_str: str, sampler=None) -> str:
        qc = self.build_circuit(input_str)
        
        if sampler:
            job = sampler.run([qc])
            result = job.result()
            pub_result = result[0]
            counts = pub_result.data.hash.get_counts()
        else:
            from qiskit import transpile
            sim = AerSimulator()
            t_qc = transpile(qc, backend=sim)
            job = sim.run(t_qc, shots=1024, seed_simulator=42)
            counts = job.result().get_counts()
            
        best_hash = max(counts, key=counts.get)
        hex_string = hex(int(best_hash, 2))[2:].upper()
        return hex_string
