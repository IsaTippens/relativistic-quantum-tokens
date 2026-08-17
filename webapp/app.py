import time
import asyncio
from flask import Flask, render_template, request, redirect, url_for, flash
import sys
import os

# Add parent dir to path so we can import entities
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from entities.bank_node import BankNode
from entities.alice_node import AliceNode
from entities.charlie_node import CharlieNode
from quantum_circuits.superdense_simulator import encode_payload, decode_payload

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Setup global instances
bank_db_path = os.path.join(os.path.dirname(__file__), 'bank.db')
bank_node = BankNode(db_path=bank_db_path)
alice_node = AliceNode()
charlie_node = CharlieNode()
charlie_payload = None

@app.route('/')
@app.route('/bank')
def bank():
    with bank_node.lock:
        bank_node.cursor.execute("SELECT serial_number, collapsed_state, status FROM ledger")
        ledger = bank_node.cursor.fetchall()
    return render_template('bank.html', ledger=ledger)

@app.route('/alice')
def alice():
    return render_template('alice.html', node=alice_node)

@app.route('/alice/request', methods=['POST'])
def alice_request():
    serial_number, shared_secret = bank_node.perform_bb84_exchange(alice_node)
    flash(f'Token requested. Serial: {serial_number}', 'success')
    return redirect(url_for('alice'))

@app.route('/alice/send', methods=['POST'])
def alice_send():
    global charlie_payload
    ttl = float(request.form.get('ttl', 5))
    target_geohash = request.form.get('target_geohash', 'u4pruydqqvj')
    expiration_timestamp = time.time() + (ttl * 60)
    
    try:
        payload = alice_node.program_token(target_geohash, expiration_timestamp)
        # Alice -> Charlie leg is transmitted via superdense coding
        charlie_payload = alice_node.send_token(payload)
        flash('Token sent to Charlie.', 'success')
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('alice'))
        
    return redirect(url_for('charlie'))

@app.route('/charlie')
def charlie():
    current_time = time.time()
    current_geohash = 'u4pruydqqvj'
    # Charlie decodes the qubits received from Alice for display
    payload = decode_payload(charlie_payload) if charlie_payload else None
    return render_template('charlie.html', payload=payload, current_time=current_time, current_geohash=current_geohash)

@app.route('/charlie/settle', methods=['POST'])
def charlie_settle():
    global charlie_payload
    if not request.form.get('serial_number'):
        flash('No payload provided', 'danger')
        return redirect(url_for('bank'))

    serial_number = request.form.get('serial_number')
    target_geohash = request.form.get('target_geohash')
    expiration_timestamp = float(request.form.get('expiration_timestamp'))
    aah_hash = request.form.get('hash')
    
    current_time = float(request.form.get('current_time'))
    current_geohash = request.form.get('current_geohash')
    
    settlement_payload = {
        'serial_number': serial_number,
        'target_geohash': target_geohash,
        'expiration_timestamp': expiration_timestamp,
        'hash': aah_hash
    }

    # The (possibly tampered) form fields are what Charlie forwards;
    # the Charlie -> Bank leg is transmitted via superdense coding
    transmission = charlie_node.channel.transmit_bits(encode_payload(settlement_payload))
    success = asyncio.run(charlie_node.receive_and_settle(
        transmission, 
        current_time, 
        current_geohash, 
        bank_node
    ))

    if success:
        flash('Settlement successful.', 'success')
    else:
        flash('Settlement rejected.', 'danger')
        
    charlie_payload = None
    return redirect(url_for('bank'))

if __name__ == '__main__':
    app.run(debug=True)