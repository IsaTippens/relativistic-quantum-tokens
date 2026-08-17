from qiskit import QuantumCircuit
from qiskit.circuit.library import ZGate

def draw_grover_linear():
    # 3 qubits for the search space, 1 auxiliary qubit or just 3 qubits
    qc = QuantumCircuit(3)
    
    # Initialization
    qc.h(range(3))
    qc.barrier()
    
    # Oracle (Linear, multi-controlled Z)
    # Marking state |111>
    qc.h(2)
    qc.mcx([0, 1], 2)
    qc.h(2)
    qc.barrier()
    
    # Diffusion operator
    qc.h(range(3))
    qc.x(range(3))
    
    # Multi-controlled Z
    qc.h(2)
    qc.mcx([0, 1], 2)
    qc.h(2)
    
    qc.x(range(3))
    qc.h(range(3))
    
    # Draw and save
    qc.draw(output='mpl', filename='thesis_figures/grover_linear.png')

if __name__ == "__main__":
    draw_grover_linear()
