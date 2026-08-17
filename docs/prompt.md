# Role & Objective
You are an expert quantum software engineer. Your task is to build an MVP/prototype Python framework for a Quantum-Secured Token Protocol. This protocol tests the feasibility of quantum communication over classical stages, acting as a relativistic / S-money hybrid.

# Tech Stack & Constraints
* **Language:** Python 3.10+
* **Quantum SDK:** Modern `qiskit` (v1.0+)
* **Simulation:** `qiskit_aer` (AerSimulator)
* **Cloud Execution:** `qiskit_ibm_runtime` (Use `SamplerV2` for dispatching circuits to IBM Quantum Cloud for benchmarking).
* **Architecture:** Object-Oriented. Strictly decouple the entities (`Bank`, `Alice`, `Charlie`).

# Protocol Outline
The token lifecycle has two stages: quantum and classical. Do not worry about financial amounts; focus on a functional cryptographic transaction process.

1. **Key Generation (Alice & Bank):** Alice and the Bank perform a simulated BB84 key exchange. This generates a shared classical secret state.
2. **Issuance:** The Bank generates a random classical Serial Number, sends it to Alice, and stores the `[Serial Number : Secret State]` in a local database/dictionary.
3. **The Spend (Alice & Charlie):** Alice visits Charlie (the merchant). Charlie provides his classical `Location` (e.g., a geohash) and `Timestamp`. 
4. **Quantum Hashing:** Alice takes her `Secret State`, `Serial Number`, `Location`, and `Timestamp`, concatenates them into a classical string, and runs it through a Quantum Hash Function (specs below). The measurement output is the classical token (hash). Alice hands the Serial Number, Hash, Location, and Time to Charlie.
5. **Settlement (Charlie & Bank):** Charlie transmits this payload to the Bank. The Bank looks up the `Secret State` using the `Serial Number`, concatenates the data, and runs the exact same Quantum Hash Function. 
6. **Verification:** If the Bank's resulting hash matches Charlie's provided hash, the transaction succeeds.

# Quantum Hash Function Specification
Implement a 1D Quantum Random Walk algorithm acting as a hash function.
* **Input:** A concatenated classical string.
* **Output:** A 4-bit classical string (the hash).
* **Circuit Design:** 
  * 4 position qubits (nodes on a cycle).
  * 1 coin qubit.
  * 4 classical registers for measurement.
* **Algorithm:** Convert the input string to bytes/binary. Loop through the binary data: use each bit to dictate the state/rotation of the coin qubit, then apply the conditional shift operator to the 4 position qubits. 
* **Measurement:** Measure the 4 position qubits at the end to generate the deterministic 4-bit hash.

# Project Structure
Create a clean, modular project layout. Please generate the necessary files and folders:

/quantum_token_project
│
├── /quantum_circuits         # Contains the Qiskit logic
│   ├── __init__.py
│   ├── bb84_simulator.py     # Logic for the BB84 key exchange
│   └── quantum_walk_hash.py  # The 4-qubit + 1-coin quantum walk hashing circuit
│
├── /entities                 # The actors in the protocol
│   ├── __init__.py
│   ├── bank.py               # Bank class (DB management, verification, Q-Hash check)
│   ├── alice_wallet.py       # Alice class (holds secret, generates token)
│   └── merchant.py           # Charlie class (provides location/time, routes to bank)
│
├── /utils                    # Helpers
│   ├── __init__.py
│   └── ibm_connector.py      # qiskit_ibm_runtime logic for cloud benchmarking
│
├── main.py                   # The orchestration script demonstrating the end-to-end flow
└── requirements.txt          # qiskit, qiskit-aer, qiskit-ibm-runtime

# Implementation Guidelines
1. **Modern Qiskit:** Do not use the deprecated `execute()` function. Use `AerSimulator().run()` for local tests, and `SamplerV2` from `qiskit_ibm_runtime` for the IBM Cloud integration.
2. **Simulated BB84:** You do not need to build a full physical optical simulation for BB84; a Qiskit circuit demonstrating prepare-and-measure with basis reconciliation is sufficient to output the shared classical bitstring.
3. **Logging:** Include standard Python `logging` in `main.py` so the terminal output clearly narrates the transaction flow step-by-step.