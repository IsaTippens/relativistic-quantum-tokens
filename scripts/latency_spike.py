import time
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from entities.bank_node import BankNode
from entities.alice_node import AliceNode
from entities.charlie_node import CharlieNode

async def main():
    bank = BankNode()
    alice = AliceNode()
    charlie = CharlieNode()
    
    t0 = time.time()
    bank.perform_bb84_exchange(alice)
    t1 = time.time()
    
    target_geohash = "gcpuy"
    exp = time.time() + 300
    
    t2 = time.time()
    payload = alice.program_token(target_geohash, exp)
    t3 = time.time()
    
    t4 = time.time()
    await charlie.receive_and_settle(alice.send_token(payload), time.time(), "gcpuy", bank)
    t5 = time.time()
    
    print(f"Issuance: {t1-t0}")
    print(f"Hashing: {t3-t2}")
    print(f"Settlement: {t5-t4}")

asyncio.run(main())
