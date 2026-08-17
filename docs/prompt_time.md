# Quantum Time Synchronisation

- Exploits the dephasing of quantum states to synchronise time between two parties.
- A central source schedules 3 measurements at times t1, t2, t3.
- Alice and Bob receive a stream of entangled qubits from the source.
- They measure the qubits at the scheduled times and record the outcomes.
- By comparing their measurement results, Alice and Bob can determine the time offset between their clocks based on the correlation of their measurements.
- A high correlation indicates good synchronisation, while a low correlation suggests a time offset that needs to be corrected.
- One or either party adjust their clocks forward or backwards after each interval until they achieve synchronisation.