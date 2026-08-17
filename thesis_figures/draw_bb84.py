from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

def draw_bb84():
    # 1 qubit for Alice/Bob communication
    q = QuantumRegister(1, 'q')
    c = ClassicalRegister(1, 'c')
    qc = QuantumCircuit(q, c)
    
    # Alice prepares state |->
    qc.x(q[0])
    qc.h(q[0])
    
    # Send to Bob
    qc.barrier()
    
    # Bob receives and measures in X basis
    qc.h(q[0])
    qc.measure(q[0], c[0])
    
    # Draw and save
    qc.draw(output='mpl', filename='thesis_figures/bb84.png')

if __name__ == "__main__":
    draw_bb84()
