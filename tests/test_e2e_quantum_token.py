import pytest
import asyncio
import time
from entities.bank_node import BankNode
from entities.alice_node import AliceNode
from entities.charlie_node import CharlieNode

@pytest.fixture
def bank_node():
    return BankNode()

@pytest.fixture
def alice_node(bank_node):
    alice = AliceNode()
    bank_node.perform_bb84_exchange(alice)
    return alice

@pytest.fixture
def charlie_node():
    return CharlieNode()

@pytest.mark.asyncio
async def test_full_settlement_flow(bank_node, alice_node, charlie_node):
    target_geohash = "gcpuy"
    expiration_timestamp = time.time() + 300
    
    # Alice programs the token
    payload = alice_node.program_token(target_geohash, expiration_timestamp)
    
    # Charlie receives and settles
    current_time = time.time()
    current_geohash = "gcpuy"
    result = await charlie_node.receive_and_settle(alice_node.send_token(payload), current_time, current_geohash, bank_node)
    
    assert result is True
    
    # Verify DB status
    bank_node.cursor.execute("SELECT status FROM ledger WHERE serial_number = ?", (payload["serial_number"],))
    status = bank_node.cursor.fetchone()[0]
    assert status == "SPENT"

@pytest.mark.asyncio
async def test_geographic_spoofing(bank_node, alice_node, charlie_node):
    target_geohash = "gcpuy"
    expiration_timestamp = time.time() + 300
    
    payload = alice_node.program_token(target_geohash, expiration_timestamp)
    
    # Charlie submits a different geohash
    current_time = time.time()
    current_geohash = "wrong"
    result = await charlie_node.receive_and_settle(alice_node.send_token(payload), current_time, current_geohash, bank_node)
    
    assert result is False

@pytest.mark.asyncio
async def test_temporal_expiration(bank_node, alice_node, charlie_node):
    target_geohash = "gcpuy"
    expiration_timestamp = time.time() + 300
    
    payload = alice_node.program_token(target_geohash, expiration_timestamp)
    
    # Charlie submits with a time > expiration
    current_time = expiration_timestamp + 10
    current_geohash = "gcpuy"
    result = await charlie_node.receive_and_settle(alice_node.send_token(payload), current_time, current_geohash, bank_node)
    
    assert result is False

@pytest.mark.asyncio
async def test_data_tampering(bank_node, alice_node, charlie_node):
    target_geohash = "gcpuy"
    expiration_timestamp = time.time() + 300
    
    payload = alice_node.program_token(target_geohash, expiration_timestamp)
    
    # Mutate expiration_timestamp in payload
    payload["expiration_timestamp"] = expiration_timestamp + 1000
    
    current_time = time.time()
    current_geohash = "gcpuy"
    result = await charlie_node.receive_and_settle(alice_node.send_token(payload), current_time, current_geohash, bank_node)
    
    assert result is False

@pytest.mark.asyncio
async def test_double_spend(bank_node, alice_node, charlie_node):
    target_geohash = "gcpuy"
    expiration_timestamp = time.time() + 300
    
    payload = alice_node.program_token(target_geohash, expiration_timestamp)
    
    current_time = time.time()
    current_geohash = "gcpuy"
    
    # Charlie submits exact same payload twice concurrently
    results = await asyncio.gather(
        charlie_node.receive_and_settle(alice_node.send_token(payload), current_time, current_geohash, bank_node),
        charlie_node.receive_and_settle(alice_node.send_token(payload), current_time, current_geohash, bank_node)
    )
    
    # One should succeed, the other should fail
    assert results.count(True) == 1
    assert results.count(False) == 1
    
    # Verify DB status
    bank_node.cursor.execute("SELECT status FROM ledger WHERE serial_number = ?", (payload["serial_number"],))
    status = bank_node.cursor.fetchone()[0]
    assert status == "SPENT"
