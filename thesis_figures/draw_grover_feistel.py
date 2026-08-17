from qiskit import QuantumCircuit, QuantumRegister
from math import pi

def draw_grover_feistel():
    # 2 qubits for left register, 2 qubits for right register
    left = QuantumRegister(2, 'L')
    right = QuantumRegister(2, 'R')
    qc = QuantumCircuit(left, right)
    
    # Initialization
    qc.h(left)
    qc.h(right)
    qc.barrier()
    
    # Feistel Round
    # Apply non-linear function (parameterized Ry, Rz) to the right register
    qc.ry(pi/4, right[0])
    qc.rz(pi/2, right[0])
    qc.ry(pi/3, right[1])
    qc.rz(pi/4, right[1])
    
    qc.barrier()
    # XOR right into left
    qc.cx(right[0], left[0])
    qc.cx(right[1], left[1])
    
    qc.barrier()
    # Swap left and right registers
    qc.swap(left[0], right[0])
    qc.swap(left[1], right[1])
    
    # Draw and save
    qc.draw(output='mpl', filename='thesis_figures/grover_feistel.png')

if __name__ == "__main__":
    draw_grover_feistel()
