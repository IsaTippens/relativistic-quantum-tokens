import numpy as np
import hashlib
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
from qiskit.quantum_info import random_unitary, Statevector
# from qiskit.circuit.library.arithmetic import Increment, Decrement # Removed
from qiskit.circuit.library import RYGate, ZGate, HGate, UnitaryGate, MCXGate
from typing import List, Tuple, Dict

# For reproducibility of "random" elements fixed for a hash function instance
FIXED_SEED = 42
rng = np.random.default_rng(FIXED_SEED)

def get_fixed_coin_angles() -> Dict[str, float]:
    """Returns a fixed set of 4 angles (theta) for the coin operators."""
    return {
        "00": rng.uniform(0.01, np.pi/2 - 0.01),
        "01": rng.uniform(0.01, np.pi/2 - 0.01),
        "10": rng.uniform(0.01, np.pi/2 - 0.01),
        "11": rng.uniform(0.01, np.pi/2 - 0.01),
    }

COIN_ANGLES_THETA = get_fixed_coin_angles()

def get_coin_operator(theta_val: float) -> UnitaryGate:
    """
    Constructs the coin operator C_i = Ry(2*theta_i) . Z
    The matrix is [[cos(theta), sin(theta)], [sin(theta), -cos(theta)]].
    """
    op_matrix = np.array([
        [np.cos(theta_val), np.sin(theta_val)],
        [np.sin(theta_val), -np.cos(theta_val)]
    ], dtype=complex)
    return UnitaryGate(op_matrix, label=f"C(th={theta_val:.2f})")

def get_fixed_cru_params(num_anc_qubits: int, num_pos_qubits: int, ensemble: str = "CUE") -> Tuple[List[UnitaryGate], List[int]]:
    """
    Generates a fixed set of 2x2 unitaries and their target position qubits
    for the Controlled Random Unitary (CRU) stage.
    """
    cru_unitaries = []
    target_pos_indices = []
    local_rng = np.random.default_rng(FIXED_SEED + 100)

    for i in range(num_anc_qubits):
        unitary = random_unitary(2, seed=local_rng.integers(1000)).to_instruction()
        unitary.label = f"{ensemble}_{i}"
        cru_unitaries.append(unitary)
        target_pos_indices.append(local_rng.integers(num_pos_qubits))
        
    return cru_unitaries, target_pos_indices

# --- Custom Incrementer and Decrementer Circuits ---
def n_qubit_incrementer_gate(num_qubits: int) -> QuantumCircuit:
    """Creates an n-qubit incrementer circuit (adds 1 modulo 2^n)."""
    qc = QuantumCircuit(num_qubits, name=f"Inc{num_qubits}")
    if num_qubits > 0:
        for i in range(num_qubits - 1, -1, -1): # From most significant to least significant
            if i == 0: # LSB
                qc.x(0)
            else:
                controls = list(range(i)) # Qubits Q_0, ..., Q_{i-1}
                qc.mcx(controls, qc.qubits[i])
    return qc

def n_qubit_decrementer_gate(num_qubits: int) -> QuantumCircuit:
    """Creates an n-qubit decrementer circuit (subtracts 1 modulo 2^n)."""
    # Inverse of incrementer
    qc_inc = n_qubit_incrementer_gate(num_qubits)
    qc_dec = qc_inc.inverse()
    qc_dec.name = f"Dec{num_qubits}"
    return qc_dec
# --- End Custom Incrementer and Decrementer ---


def fqh_banerjee_paper_implementation(
    input_message_bits: str,
    num_pos_qubits: int,
    num_anc_qubits_q: int, # 'q' from the paper for the ancilla register
    params_fixed: bool = True
) -> str:
    if not input_message_bits:
        raise ValueError("Input message cannot be empty.")
    
    processed_message = list(input_message_bits)
    if len(processed_message) % 2 != 0:
        processed_message.append("0")
    
    num_walk_steps = len(processed_message) // 2

    if params_fixed:
        coin_angles = COIN_ANGLES_THETA
        cru_unitaries, cru_target_pos_indices = get_fixed_cru_params(num_anc_qubits_q, num_pos_qubits)
    else: 
        temp_rng = np.random.default_rng()
        coin_angles = {
            "00": temp_rng.uniform(0.01, np.pi/2 - 0.01), "01": temp_rng.uniform(0.01, np.pi/2 - 0.01),
            "10": temp_rng.uniform(0.01, np.pi/2 - 0.01), "11": temp_rng.uniform(0.01, np.pi/2 - 0.01)
        }
        cru_unitaries, cru_target_pos_indices = [], []
        for i in range(num_anc_qubits_q):
            cru_unitaries.append(random_unitary(2, seed=temp_rng.integers(1000)).to_instruction())
            cru_target_pos_indices.append(temp_rng.integers(num_pos_qubits))

    pos_q = QuantumRegister(num_pos_qubits, name='pos')
    coin_q = QuantumRegister(1, name='coin')
    # msg_q conceptually exists but is implemented by choosing the coin_op
    anc_q = QuantumRegister(num_anc_qubits_q, name='anc')
    final_meas_c = ClassicalRegister(num_anc_qubits_q, name='hash_basis')
    
    qc = QuantumCircuit(pos_q, coin_q, anc_q, final_meas_c) # Removed msg_q from here

    # Get incrementer and decrementer gates
    increment_gate = n_qubit_incrementer_gate(num_pos_qubits).to_gate()
    decrement_gate = n_qubit_decrementer_gate(num_pos_qubits).to_gate()

    controlled_increment_op = increment_gate.control(1)
    controlled_decrement_op = decrement_gate.control(1)

    for step in range(num_walk_steps):
        bit1_idx = step * 2
        bit2_idx = step * 2 + 1
        current_msg_chunk_str = processed_message[bit1_idx] + processed_message[bit2_idx]
        
        theta_i = coin_angles[current_msg_chunk_str]
        coin_op_gate = get_coin_operator(theta_i)
        qc.append(coin_op_gate, [coin_q[0]])
        qc.barrier()
        
        # Shift if coin is |0> (e.g., decrement, following Fig 1 logic of tail=anticlockwise)
        qc.x(coin_q[0]) 
        qc.append(controlled_decrement_op, [coin_q[0]] + list(pos_q))
        qc.x(coin_q[0])

        # Shift if coin is |1> (e.g., increment, Fig 1 head=clockwise)
        qc.append(controlled_increment_op, [coin_q[0]] + list(pos_q))
        qc.barrier()

    for i in range(num_anc_qubits_q):
        qc.h(anc_q[i])
    qc.barrier()

    for j in range(num_anc_qubits_q):
        target_pos_qubit_index = cru_target_pos_indices[j]
        controlled_cru = cru_unitaries[j].control(1)
        qc.append(controlled_cru, [anc_q[j], pos_q[target_pos_qubit_index]])
    qc.barrier()

    for i in range(num_anc_qubits_q):
        qc.h(anc_q[i])
    qc.barrier()
    
    qc.measure(anc_q, final_meas_c)

    # Use Statevector for exact probabilities as per paper's simulation method
    # For this, we need to simulate the circuit *without* the final measurement
    # and then calculate probabilities from the statevector.
    qc_for_statevector = qc.copy()
    qc_for_statevector.remove_final_measurements(inplace=True) # Qiskit Terra 0.23+
    
    statevector_sim = Statevector(qc_for_statevector)
    anc_q_indices = [qc_for_statevector.find_bit(q).index for q in anc_q]
    prob_dict = statevector_sim.probabilities_dict(qargs=anc_q_indices)

    sorted_basis_states = sorted(prob_dict.items(), key=lambda item: item[1], reverse=True)
    
    final_hash_binary_list = []
    for basis_state_str, prob in sorted_basis_states:
        final_hash_binary_list.append(basis_state_str)
        
    observed_states = {s for s, p in sorted_basis_states}
    num_possible_states = 2**num_anc_qubits_q
    if len(observed_states) < num_possible_states:
        all_possible_states_strs = [format(i, f'0{num_anc_qubits_q}b') for i in range(num_possible_states)]
        missing_states = [s for s in all_possible_states_strs if s not in observed_states]
        for missing_s in sorted(missing_states): 
            final_hash_binary_list.append(missing_s)
            
    final_hash_binary = "".join(final_hash_binary_list)
    
    expected_len = num_anc_qubits_q * num_possible_states
    if len(final_hash_binary) != expected_len:
        # This ensures the output hash is always the correct length, padding if necessary.
        # Essential for consistent hash output.
        all_states_ordered_lexicographically = [format(i, f'0{num_anc_qubits_q}b') for i in range(num_possible_states)]
        
        # Create a dictionary of observed states and their original index in the sorted list
        # This helps maintain the primary sort order by probability for observed states.
        observed_map = {state: idx for idx, (state, prob) in enumerate(sorted_basis_states)}
        
        # Reconstruct the full list ensuring all states are present, maintaining original sort for observed,
        # and appending unobserved ones (sorted lexicographically among themselves).
        reconstructed_list = ["" for _ in range(num_possible_states)]
        
        # Place observed states
        for state, prob in sorted_basis_states:
            # This logic assumes sorted_basis_states itself has 2^q elements
            # after padding with P=0 states. The simpler loop should be fine.
            pass # The previous loop `final_hash_binary_list.append(missing_s)` handles this

        # If the `final_hash_binary_list` isn't full, it means some states were not in prob_dict
        # and also not added by the `missing_states` loop (which shouldn't happen if logic is correct).
        # The critical part is that `final_hash_binary_list` must contain all 2^q q-bit strings,
        # sorted by probability, then by some tie-breaking rule (e.g. lexicographical for P=0 states).
        # The current construction of `final_hash_binary_list` should correctly achieve this.
        # If it's shorter than 2^q elements, the `join` will be too short.
        
        # Let's ensure final_hash_binary_list has 2^q elements
        current_output_states = {s for s in final_hash_binary_list}
        if len(final_hash_binary_list) < num_possible_states:
             all_possible_qbit_strings = [format(i, f'0{num_anc_qubits_q}b') for i in range(num_possible_states)]
             additional_needed_states = [s for s in all_possible_qbit_strings if s not in current_output_states]
             final_hash_binary_list.extend(sorted(additional_needed_states)) # Add remaining states, sorted

        final_hash_binary = "".join(final_hash_binary_list) # Re-join

        if len(final_hash_binary) != expected_len: # Final check
             print(f"CRITICAL Warning: Hash length still mismatch. Expected {expected_len}, got {len(final_hash_binary)}. Forcing length.")
             # This part is a fallback, ideally the logic above handles it.
             temp_full_list_lex = [format(i, f'0{num_anc_qubits_q}b') for i in range(num_possible_states)]
             # This simple join is WRONG as it doesn't respect probability sorting.
             # The issue is ensuring final_hash_binary_list has 2^q q-bit strings in the correct order.
             # My sorting and padding logic should ensure final_hash_binary_list has 2^q elements.

             # Re-check the logic for constructing `final_hash_binary_list`
             # 1. Get `prob_dict` for `anc_q`.
             # 2. `sorted_basis_states` = list of (state_string, probability) sorted by probability.
             # 3. Need to ensure all 2^q states are represented.
             
             # Simpler way to ensure all states are present for sorting:
             all_q_bit_strings = [format(i, f'0{num_anc_qubits_q}b') for i in range(num_possible_states)]
             full_prob_dist = []
             for s_str in all_q_bit_strings:
                 full_prob_dist.append((s_str, prob_dict.get(s_str, 0.0))) # Get P(s), or 0 if not in dict
             
             # Now sort this full list by probability, then by string value for tie-breaking
             fully_sorted_basis_states = sorted(full_prob_dist, key=lambda item: (-item[1], item[0])) # -P for descending

             final_hash_binary_list_corrected = [s_str for s_str, prob in fully_sorted_basis_states]
             final_hash_binary = "".join(final_hash_binary_list_corrected)
             
             if len(final_hash_binary) != expected_len:
                  raise RuntimeError(f"Fatal hash length error. Expected {expected_len}, got {len(final_hash_binary)}")


    return final_hash_binary

def binary_to_hex(binary_string):
    if not binary_string: return ""
    if len(binary_string) % 4 != 0:
        binary_string = '0' * (4 - len(binary_string) % 4) + binary_string
    
    hex_string = ""
    for i in range(0, len(binary_string), 4):
        chunk = binary_string[i:i+4]
        hex_val = hex(int(chunk, 2))[2:]
        hex_string += hex_val
    return hex_string.upper()

class FullQuantumHash:
    def __init__(self, num_pos_qubits=5, num_anc_qubits=5):
        self.num_pos_qubits = num_pos_qubits
        self.num_anc_qubits = num_anc_qubits

    def _string_to_binary(self, input_str: str) -> str:
        hash_bytes = hashlib.sha256(input_str.encode('utf-8')).digest()
        bin_str = bin(int.from_bytes(hash_bytes, 'big'))[2:].zfill(256)
        return bin_str[:64] # Limit to 64 steps to maintain performance

    def compute_hash(self, input_str: str, sampler=None) -> str:
        # Note: This implementation relies on Statevector probabilities
        # and not sampling. Thus, sampler is ignored here.
        bin_str = self._string_to_binary(input_str)
        binary_hash = fqh_banerjee_paper_implementation(
            input_message_bits=bin_str,
            num_pos_qubits=self.num_pos_qubits,
            num_anc_qubits_q=self.num_anc_qubits,
            params_fixed=True
        )
        return binary_to_hex(binary_hash)