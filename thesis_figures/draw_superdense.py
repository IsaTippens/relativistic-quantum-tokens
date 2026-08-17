from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

def draw_superdense():
    alice = QuantumRegister(1, 'Alice')
    bob = QuantumRegister(1, 'Bob')
    c = ClassicalRegister(2, 'c')
    qc = QuantumCircuit(alice, bob, c)
    
    # Shared Bell pair
    qc.h(alice[0])
    qc.cx(alice[0], bob[0])
    qc.barrier()
    
    # Alice encodes '11'
    qc.x(alice[0])
    qc.z(alice[0])
    
    qc.barrier()
    
    # Bob decodes
    qc.cx(alice[0], bob[0])
    qc.h(alice[0])
    
    qc.barrier()
    
    # Measurement
    qc.measure(alice[0], c[0])
    qc.measure(bob[0], c[1])
    
    # Draw and save
    qc.draw(output='mpl', filename='thesis_figures/superdense.png')

if __name__ == "__main__":
    draw_superdense()
