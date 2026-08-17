from qiskit import QuantumCircuit

def draw_qcs():
    qc = QuantumCircuit(2, 2)
    
    # Prepare Bell state |Phi+>
    qc.h(0)
    qc.cx(0, 1)
    
    # Apply delay to Bob's qubit
    qc.delay(100, 1, unit='ns')
    
    qc.barrier()
    
    # Measure in standard basis
    qc.measure([0, 1], [0, 1])
    
    # Draw and save
    qc.draw(output='mpl', filename='thesis_figures/qcs.png')

if __name__ == "__main__":
    draw_qcs()
