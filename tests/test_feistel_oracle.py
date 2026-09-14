"""Contract tests for the Feistel non-linear Grover oracle.

The oracle must satisfy, for every basis state of the search register:

    U |x> |0>_anc = (-1)^[f(x) == target] |x> |0>_anc

with f a *bijection* (Feistel invariant) that is *not* affine over GF(2)
(otherwise the "non-linear oracle" is linear and the Toffoli layer is absent).
"""
import numpy as np
import pytest
from qiskit.quantum_info import Operator, Statevector

from quantum_circuits.grover_hash import GroverNonLinearHash
from quantum_circuits.non_linear_oracle import (
    GOLDEN_RATIO_32,
    feistel_ancilla_count,
    feistel_oracle,
    feistel_permutation,
    feistel_permute,
    feistel_round_key,
    recommended_rounds,
)

WIDTHS = (3, 4, 8)


def _image(n: int, rounds: int) -> list[int]:
    return [feistel_permute(x, n, rounds) for x in range(1 << n)]


@pytest.mark.parametrize("n", WIDTHS)
def test_permutation_is_bijective(n):
    outs = _image(n, recommended_rounds(n))
    assert len(set(outs)) == 1 << n


@pytest.mark.parametrize("n", WIDTHS)
def test_permutation_is_not_affine(n):
    """A CNOT/NOT-only network is affine; the Toffoli layer must break that."""
    outs = _image(n, recommended_rounds(n))
    f0 = outs[0]
    assert not all(outs[a ^ b] == outs[a] ^ outs[b] ^ f0
                   for a in range(1 << n) for b in range(1 << n))


@pytest.mark.parametrize("n", WIDTHS)
def test_every_output_bit_depends_on_every_input_bit(n):
    outs = _image(n, recommended_rounds(n))
    dep = [[False] * n for _ in range(n)]
    for i in range(n):
        for x in range(1 << n):
            diff = outs[x] ^ outs[x ^ (1 << i)]
            for j in range(n):
                if (diff >> j) & 1:
                    dep[j][i] = True
    missing = [(j, i) for j in range(n) for i in range(n) if not dep[j][i]]
    assert not missing, f"n={n} output/input pairs with no dependency: {missing}"


@pytest.mark.parametrize("n", WIDTHS)
def test_avalanche_close_to_half_the_output_width(n):
    """A single input-bit flip should change about half the output bits."""
    rounds = recommended_rounds(n)
    outs = _image(n, rounds)
    flips = [bin(outs[x] ^ outs[x ^ (1 << i)]).count("1")
             for i in range(n) for x in range(1 << n)]
    mean = sum(flips) / len(flips)
    assert abs(mean - n / 2) <= 0.55, f"n={n} avalanche {mean:.2f}, ideal {n / 2}"


@pytest.mark.parametrize("n", (3, 4))
def test_circuit_matches_classical_reference_and_clears_ancillas(n):
    rounds = recommended_rounds(n)
    h = feistel_ancilla_count(n)
    perm = feistel_permutation(n, rounds)
    assert perm.num_qubits == n + h
    for x in range(1 << n):
        out = Statevector.from_int(x, dims=(2,) * (n + h)).evolve(perm).data
        idx = int(np.argmax(np.abs(out)))
        assert abs(out[idx] - 1.0) < 1e-9, "not a permutation of basis states"
        assert idx >> n == 0, "ancillas left dirty"
        assert idx & ((1 << n) - 1) == feistel_permute(x, n, rounds)


@pytest.mark.parametrize("n", (3, 4))
def test_oracle_is_a_phase_oracle(n):
    rounds = recommended_rounds(n)
    h = feistel_ancilla_count(n)
    target = feistel_permute(1, n, rounds)
    oracle = feistel_oracle(n, target, rounds)
    assert Operator(oracle).is_unitary()

    marked = 0
    for x in range(1 << n):
        out = Statevector.from_int(x, dims=(2,) * (n + h)).evolve(oracle).data
        expected = -1.0 if feistel_permute(x, n, rounds) == target else 1.0
        marked += expected < 0
        amp = out[x]
        assert abs(amp - expected) < 1e-9, f"x={x} amplitude {amp}, expected {expected}"
        assert np.allclose(np.delete(out, x), 0, atol=1e-9), "leaked out of |x>|0>"
    assert marked == 1, "a bijection has exactly one preimage per target"


def test_round_keys_use_the_golden_ratio_and_never_shift_negatively():
    assert GOLDEN_RATIO_32 == 0x9E3779B9
    for width in range(1, 65):
        key = feistel_round_key(0, width)
        assert 0 <= key < (1 << width)
    # distinct rounds must not collapse to the same constant
    keys = [feistel_round_key(r, 8) for r in range(4)]
    assert len(set(keys)) > 1
    with pytest.raises(ValueError):
        feistel_round_key(0, 0)


def test_oracle_rejects_out_of_range_targets():
    with pytest.raises(ValueError):
        feistel_oracle(4, 16)
    with pytest.raises(ValueError):
        feistel_permutation(2)


# Optimal Grover rotation for exactly one marked state out of 2^n:
# round(pi/4 * sqrt(2^n)). A bijective f has exactly one preimage per target,
# so the standard count applies: 2 for n=3, 3 for n=4.
OPTIMAL_ITERATIONS = {3: 2, 4: 3}


@pytest.mark.parametrize("n", (3, 4))
def test_grover_amplifies_the_feistel_preimage(n):
    """End-to-end: the hash must concentrate on f^-1(block), not on noise."""
    rounds = recommended_rounds(n)
    hasher = GroverNonLinearHash(hash_length=n, rounds=rounds,
                                 grover_iterations=OPTIMAL_ITERATIONS[n])
    message = "10110010"  # single 8-bit block -> one Grover stage
    circuit = hasher.build_circuit(message)
    assert circuit.num_qubits == n + feistel_ancilla_count(n)

    target = int(message, 2) % (1 << n)
    preimage = next(x for x in range(1 << n) if feistel_permute(x, n, rounds) == target)

    from qiskit import transpile
    from qiskit_aer import AerSimulator
    sim = AerSimulator()
    counts = sim.run(transpile(circuit, sim), shots=4096, seed_simulator=7).result().get_counts()
    top = max(counts, key=counts.get)
    assert int(top, 2) == preimage, f"top {top} != preimage {preimage:0{n}b}"
    assert counts[top] / 4096 > 0.5, "amplification did not concentrate on the preimage"


def test_odd_and_even_widths_are_supported():
    for n in (3, 4, 5, 8):
        hasher = GroverNonLinearHash(hash_length=n)
        assert hasher.build_circuit("test").num_qubits == n + n // 2
    with pytest.raises(ValueError):
        GroverNonLinearHash(hash_length=2)
