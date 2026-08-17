import sqlite3
import uuid
import asyncio
import threading
from quantum_circuits.bb84_simulator import BB84Simulator
from quantum_circuits.grover_hash import GroverHash
from quantum_circuits.superdense_simulator import SuperdenseSimulator, decode_payload

class BankNode:
    def __init__(self, db_path=':memory:'):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.channel = SuperdenseSimulator()
        self._init_db()
        self.lock = threading.Lock()

    def _init_db(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS ledger (
                serial_number TEXT PRIMARY KEY,
                bases TEXT,
                collapsed_state TEXT,
                status TEXT
            )
        ''')
        self.conn.commit()

    def perform_bb84_exchange(self, alice):
        # Generate shared secret using BB84 simulator
        simulator = BB84Simulator()
        shared_secret = simulator.generate_shared_secret()
        
        # Issue serial number
        serial_number = str(uuid.uuid4())
        self.issue_serial_number(serial_number, shared_secret)
        
        # In a real protocol Alice would participate, here we just return it to her
        alice.shared_secret = shared_secret
        alice.serial_number = serial_number
        return serial_number, shared_secret

    def issue_serial_number(self, serial_number, shared_secret):
        self.cursor.execute(
            "INSERT INTO ledger (serial_number, bases, collapsed_state, status) VALUES (?, ?, ?, ?)",
            (serial_number, '', shared_secret, 'ACTIVE')
        )
        self.conn.commit()

    async def verify_settlement(self, transmission: str, hash_length: int = 4):
        with self.lock:
            # Decode the qubits received from Charlie (superdense coding)
            payload = decode_payload(transmission)

            serial_number = payload.get('serial_number')
            target_geohash = payload.get('target_geohash')
            expiration_timestamp = payload.get('expiration_timestamp')
            aah_hash = payload.get('hash')
            current_time = payload.get('current_time')
            current_geohash = payload.get('current_geohash')

            if not all([serial_number, target_geohash, expiration_timestamp, aah_hash, current_time, current_geohash]):
                return False

            self.cursor.execute("SELECT collapsed_state, status FROM ledger WHERE serial_number = ?", (serial_number,))
            row = self.cursor.fetchone()

            if not row:
                return False

            shared_secret, status = row

            if status == 'SPENT':
                return False

            # The all() guard above rejects missing fields, so both are floats here
            if float(current_time) > float(expiration_timestamp):
                return False
                
            if current_geohash != target_geohash:
                return False

            # Reconstruct the AAH string
            # Convention: shared_secret + serial_number + target_geohash + str(expiration_timestamp)
            input_str = f"{shared_secret}{serial_number}{target_geohash}{expiration_timestamp}"
            
            # Using provided hash_length to speed up tests/benchmarks
            expected_hash = GroverHash(hash_length=hash_length).compute_hash(input_str)
            
            if aah_hash != expected_hash:
                return False

            # Update status
            self.cursor.execute("UPDATE ledger SET status = 'SPENT' WHERE serial_number = ?", (serial_number,))
            self.conn.commit()
            
            return True
