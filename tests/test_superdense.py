import random
import pytest
from quantum_circuits.superdense_simulator import SuperdenseSimulator, encode_payload, decode_payload


@pytest.fixture
def channel():
    return SuperdenseSimulator()


def test_all_two_bit_messages(channel):
    # Each Bell pair must faithfully carry both classical bits
    for bits in ['00', '01', '10', '11']:
        assert channel.transmit_bits(bits) == bits


def test_arbitrary_bitstring_roundtrip(channel):
    bits = ''.join(random.choice('01') for _ in range(257))  # odd length exercises padding
    assert channel.transmit_bits(bits) == bits


def test_two_bits_per_qubit(channel):
    # Superdense coding: n classical bits are carried on n/2 transmitted qubits
    bits = '10110010'
    qc = channel._build_circuit(bits)
    assert qc.num_qubits == len(bits)


def test_payload_roundtrip(channel):
    payload = {
        'serial_number': 'abc-123',
        'target_geohash': 'gcpuy',
        'expiration_timestamp': 1234567.89,
        'hash': '0110',
    }
    received = channel.transmit_payload(payload)
    assert received == payload
    # Bit-level API agrees with the payload codec
    assert decode_payload(channel.transmit_bits(encode_payload(payload))) == payload


def test_tampered_qubit_corrupts_payload(channel):
    payload = {'serial_number': 'abc-123', 'hash': '0110'}
    transmission = channel.transmit_bits(encode_payload(payload))

    # Adversary flips one transmitted bit (e.g. wrong gate applied to a qubit)
    tampered = list(transmission)
    tampered[0] = '1' if tampered[0] == '0' else '0'
    tampered = ''.join(tampered)

    with pytest.raises(Exception):
        decode_payload(tampered)
