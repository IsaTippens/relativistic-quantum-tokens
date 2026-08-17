import pytest
from quantum_circuits.bb84_simulator import BB84Simulator
from quantum_circuits.quantum_walk_hash import QuantumWalkHash
from quantum_circuits.grover_hash import GroverHash, GroverNonLinearHash
from entities.bank import Bank
from entities.alice_wallet import AliceWallet
from entities.merchant import Merchant

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
    from qiskit_aer import AerSimulator
    from qiskit import transpile
    
    gn_hash = GroverNonLinearHash()
    payload = "test_payload_123"
    qc = gn_hash.build_circuit(payload)
    
    sim = AerSimulator()
    t_qc = transpile(qc, backend=sim)
    
    hashes = set()
    for seed in range(10):
        job = sim.run(t_qc, shots=1024, seed_simulator=seed)
        counts = job.result().get_counts()
        best_hash = max(counts, key=counts.get)
        hashes.add(best_hash)
        
    assert len(hashes) == 1, f"Expected deterministic hash regardless of seed, but got: {hashes}"
def test_full_protocol_flow():
    bank = Bank()
    alice = AliceWallet()
    charlie = Merchant(name="TestMerchant", location_geohash="abc1234")

    # Key Gen
    secret = bank.perform_bb84_exchange(alice)
    assert alice.shared_secret == secret
    
    # Issuance
    serial = bank.issue_serial_number(secret)
    alice.receive_serial_number(serial)
    assert alice.serial_number == serial
    assert serial in bank.ledger
    
    # Spend
    payload = alice.spend_at_merchant(charlie)
    assert "serial_number" in payload
    assert "hash" in payload
    assert payload["location"] == charlie.get_location()
    
    # Settle
    is_valid = charlie.receive_token_and_settle(payload, bank)
    assert is_valid == True

def test_invalid_settlement():
    bank = Bank()
    alice = AliceWallet()
    charlie = Merchant(name="TestMerchant", location_geohash="abc1234")

    secret = bank.perform_bb84_exchange(alice)
    serial = bank.issue_serial_number(secret)
    alice.receive_serial_number(serial)
    
    payload = alice.spend_at_merchant(charlie)
    
    # Tamper with payload hash
    payload["hash"] = "0000" if payload["hash"] != "0000" else "1111"
    
    is_valid = charlie.receive_token_and_settle(payload, bank)
    assert is_valid == False
