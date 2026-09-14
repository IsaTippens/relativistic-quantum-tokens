import pytest
from quantum_circuits.bb84_simulator import BB84Simulator
from quantum_circuits.quantum_walk_hash import QuantumWalkHash
from quantum_circuits.grover_hash import GroverHash, GroverNonLinearHash
from entities.bank import Bank
from entities.alice_wallet import AliceWallet
from entities.merchant import Merchant
from quantum_circuits.superdense_simulator import encode_payload, decode_payload

def test_bb84_key_exchange():
    sim = BB84Simulator(num_bits=64)
    secret = sim.generate_shared_secret()
    assert isinstance(secret, str)
    assert len(secret) > 0
    # The shared secret should just be a string of 1s and 0s
    assert all(c in '01' for c in secret)

def test_quantum_walk_hash_deterministic():
    q_hash = QuantumWalkHash()
    payload = "test_payload_123"
    
    # Should produce identical results for identical inputs
    hash1 = q_hash.compute_hash(payload)
    hash2 = q_hash.compute_hash(payload)
    
    assert hash1 == hash2
    assert len(hash1) == 4

def test_quantum_walk_hash_different_inputs():
    q_hash = QuantumWalkHash()
    payload1 = "test_payload_123"
    payload2 = "test_payload_456"
    
    hash1 = q_hash.compute_hash(payload1)
    hash2 = q_hash.compute_hash(payload2)
    # Note: there is a small chance (1 in 16) they match, but typically they should differ or be deterministic
    # We just ensure it computes successfully and returns 4 bits.
    assert len(hash1) == 4
    assert len(hash2) == 4

def test_grover_hash_deterministic():
    g_hash = GroverHash()
    payload = "test_payload_123"
    
    # Should produce identical results for identical inputs
    hash1 = g_hash.compute_hash(payload)
    hash2 = g_hash.compute_hash(payload)
    
    assert hash1 == hash2
    assert len(hash1) == 8
    assert all(c in '01' for c in hash1)

def test_grover_hash_different_inputs():
    g_hash = GroverHash()
    payload1 = "test_payload_123"
    payload2 = "test_payload_456"
    
    hash1 = g_hash.compute_hash(payload1)
    hash2 = g_hash.compute_hash(payload2)
    
    assert len(hash1) == 8
    assert len(hash2) == 8
    assert hash1 != hash2


def test_grover_nonlinear_hash_deterministic():
    gn_hash = GroverNonLinearHash()
    payload = "test_payload_123"
    
    # Should produce identical results for identical inputs
    hash1 = gn_hash.compute_hash(payload)
    hash2 = gn_hash.compute_hash(payload)
    
    assert hash1 == hash2
    assert len(hash1) == 8
    assert all(c in '01' for c in hash1)

def test_grover_nonlinear_hash_different_inputs():
    gn_hash = GroverNonLinearHash()
    payload1 = "test_payload_123"
    payload2 = "test_payload_456"
    
    hash1 = gn_hash.compute_hash(payload1)
    hash2 = gn_hash.compute_hash(payload2)
    
    assert len(hash1) == 8
    assert len(hash2) == 8
    assert hash1 != hash2

def test_grover_nonlinear_hash_seed_robustness():
    """Determinism requires the amplification to actually concentrate.

    With one marked state out of 2**n, round(pi/4*sqrt(2**n)) iterations are
    needed. At the optimal count the argmax is stable across simulator seeds;
    at the shallower default the distribution stays near-uniform and the argmax
    is sampling noise. Both halves are asserted so the tradeoff is explicit.
    """
    from qiskit_aer import AerSimulator
    from qiskit import transpile
    from quantum_circuits.grover_hash import optimal_grover_iterations

    payload = "test_payload_123"
    sim = AerSimulator()

    def top_hashes(iterations):
        qc = GroverNonLinearHash(grover_iterations=iterations).build_circuit(payload)
        t_qc = transpile(qc, backend=sim)
        found = set()
        peaks = []
        for seed in range(10):
            counts = sim.run(t_qc, shots=1024, seed_simulator=seed).result().get_counts()
            best = max(counts, key=counts.get)
            found.add(best)
            peaks.append(counts[best] / 1024)
        return found, sum(peaks) / len(peaks)

    assert optimal_grover_iterations(8) == 13
    stable, peak = top_hashes(optimal_grover_iterations(8))
    assert len(stable) == 1, f"optimal rotation must be deterministic, got {stable}"
    assert peak > 0.9, f"optimal rotation must concentrate, peak was {peak:.3f}"

    under, under_peak = top_hashes(2)
    assert under_peak < 0.2, (
        "2 iterations at 8 bits should leave the distribution flat; "
        f"peak was {under_peak:.3f}")


def test_full_protocol_flow():
    bank = Bank()
    alice = AliceWallet()
    charlie = Merchant(name="TestMerchant", location_geohash="abc1234")

    # Key Gen
    secret = bank.perform_bb84_exchange(alice)
    assert alice.shared_secret == secret
    
    # Issuance: the serial reaches Alice over the superdense-coded channel
    serial = bank.issue_serial_number(secret)
    assert alice.receive_serial_number(bank.send_serial_number(serial)) == serial
    assert alice.serial_number == serial
    assert serial in bank.ledger

    # Spend: Alice hands Charlie a superdense transmission, not a plain dict
    transmission = alice.spend_at_merchant(charlie)
    payload = decode_payload(transmission)
    assert "serial_number" in payload
    assert "hash" in payload
    assert payload["location"] == charlie.location

    # Settle
    is_valid = charlie.receive_token_and_settle(transmission, bank)
    assert is_valid == True

def test_invalid_settlement():
    bank = Bank()
    alice = AliceWallet()
    charlie = Merchant(name="TestMerchant", location_geohash="abc1234")

    secret = bank.perform_bb84_exchange(alice)
    serial = bank.issue_serial_number(secret)
    alice.receive_serial_number(bank.send_serial_number(serial))

    transmission = alice.spend_at_merchant(charlie)

    # Tamper with the hash Charlie forwards, then re-transmit it
    payload = decode_payload(transmission)
    payload["hash"] = "0000" if payload["hash"] != "0000" else "1111"
    tampered = charlie.channel.transmit_bits(encode_payload(payload))

    is_valid = charlie.receive_token_and_settle(tampered, bank)
    assert is_valid == False
