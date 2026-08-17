import random
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator

class BB84Simulator:
    """
    Simulates a BB84 Key Exchange to generate a shared secret state.
    """
    def __init__(self, num_bits: int = 128):
        self.num_bits = num_bits
        self.simulator = AerSimulator()

    def generate_shared_secret(self) -> str:
        """
        Executes the BB84 protocol simulation and returns a shared bitstring.
        """
        # 1. Alice chooses random bits and bases
        alice_bits = [random.choice([0, 1]) for _ in range(self.num_bits)]
        alice_bases = [random.choice(['Z', 'X']) for _ in range(self.num_bits)]

        # 2. Bank chooses random bases
        bank_bases = [random.choice(['Z', 'X']) for _ in range(self.num_bits)]

        # 3. Simulate the quantum channel
        qc = QuantumCircuit(1, 1)
        bank_results = []

        for i in range(self.num_bits):
            qc.clear()
            
            # Alice prepares qubit
            if alice_bits[i] == 1:
                qc.x(0)
            if alice_bases[i] == 'X':
                qc.h(0)

            # Bank measures qubit
            if bank_bases[i] == 'X':
                qc.h(0)
            qc.measure(0, 0)

            result = self.simulator.run(qc, shots=1).result()
            measured_bit = int(list(result.get_counts().keys())[0])
            bank_results.append(measured_bit)

        # 4. Sift the key (basis reconciliation)
        shared_key = []
        for i in range(self.num_bits):
            if alice_bases[i] == bank_bases[i]:
                # In a real protocol, we'd check a subset for eavesdropping.
                shared_key.append(str(alice_bits[i]))

        # Return the shared secret as a binary string
        return "".join(shared_key)
