"""Non-linear Grover oracle built from a reversible Feistel network.

Replaces the identity-style oracle of :class:`GroverHash` (which marks the
input index itself) with one that marks ``f(x)``, where ``f`` is a Feistel
permutation. Only NOT, CNOT and Toffoli gates are used, so the whole network
is a permutation of the computational basis and Grover's diffusion operator is
untouched.

Structure of one round, on a register split into ``L`` (low ``h = n // 2``
qubits of the current wire order) and ``R`` (remaining ``m = n - h`` qubits):

    anc  ^= F_r(R)          # CNOT + Toffoli + NOT, R as controls
    L    ^= anc             # CNOT
    anc  ^= F_r(R)          # same block replayed -> ancilla back to |0>
    wire order <<= h        # cyclic rotation; for even n this is the L/R swap

``F_r(R)_i = R_{i mod m} XOR (R_{(i+1) mod m} AND R_{(i+2) mod m}) XOR k_{r,i}``

The AND term is the Toffoli, and it is what makes ``f`` non-linear over GF(2);
without it the whole network collapses to an affine map. ``k_r`` is derived
from the golden-ratio constant 0x9E3779B9.

The cyclic rotation (rather than a strict half swap) makes odd ``n`` work as an
unbalanced Feistel network, so 3-bit hashes are supported alongside 4 and 8.

Grover oracle contract, satisfied by :func:`feistel_oracle`:

    U |x> |0>_anc  =  (-1)^[f(x) == target] |x> |0>_anc

i.e. ``f`` is computed, the phase is applied on the target, and ``f`` is
inverted, leaving the search register in the ``x`` basis with clean ancillas.
"""
from __future__ import annotations

from qiskit import AncillaRegister, QuantumCircuit, QuantumRegister

GOLDEN_RATIO_32 = 0x9E3779B9
"""Knuth's golden-ratio constant, 2^32 / phi, the standard Feistel mixer."""


def feistel_round_key(round_index: int, width: int) -> int:
    """Round constant for round ``round_index`` folded to ``width`` bits.

    The multiply is truncated to 32 bits (as the constant intends) and then
    folded by XOR into ``width`` bits, so every bit of the constant reaches the
    key for any width and no shift is ever negative.
    """
    if width <= 0:
        raise ValueError("width must be positive")
    prod = (GOLDEN_RATIO_32 * (round_index + 1)) & 0xFFFFFFFF
    mask = (1 << width) - 1
    if width <= 32:
        key = 0
        for offset in range(0, 32, width):
            key ^= prod >> offset
        return key & mask
    key, acc = 0, prod
    for offset in range(0, width, 32):
        acc = (acc * GOLDEN_RATIO_32 + GOLDEN_RATIO_32) & 0xFFFFFFFF
        key |= acc << offset
    return key & mask


def _split(n: int) -> tuple[int, int]:
    """(h, m): width of the L target half and of the R source half."""
    h = n // 2
    return h, n - h


def feistel_permute(x: int, n: int, rounds: int = 4) -> int:
    """Classical reference for the permutation the circuit applies.

    Bit ``i`` of the returned integer is the value left on qubit ``i``.
    """
    if n < 3:
        raise ValueError("n must be at least 3")
    h, m = _split(n)
    bits = [(x >> i) & 1 for i in range(n)]
    wires = list(range(n))
    for r in range(rounds):
        left, right = wires[:h], wires[h:]
        key = feistel_round_key(r, h)
        # All h round-function outputs are computed from the pre-round R, which
        # the L updates cannot touch (L and R are disjoint).
        for i in range(h):
            val = (bits[right[i % m]]
                   ^ (bits[right[(i + 1) % m]] & bits[right[(i + 2) % m]])
                   ^ ((key >> i) & 1))
            bits[left[i]] ^= val
        wires = wires[h:] + wires[:h]
    return sum(b << i for i, b in enumerate(bits))


def _round_function(qc: QuantumCircuit, right, anc, key: int, h: int, m: int) -> None:
    """anc ^= F_r(right). Self-inverse: replaying it clears the ancilla."""
    for i in range(h):
        qc.cx(right[i % m], anc[i])
        qc.ccx(right[(i + 1) % m], right[(i + 2) % m], anc[i])
        if (key >> i) & 1:
            qc.x(anc[i])


def feistel_permutation(n: int, rounds: int = 4) -> QuantumCircuit:
    """Circuit computing ``f`` in place on ``n`` qubits, ancillas returned to |0>.

    Register layout: QuantumRegister("x", n) then AncillaRegister("fa", n // 2).
    """
    if n < 3:
        raise ValueError("n must be at least 3 for a Feistel network")
    if rounds < 1:
        raise ValueError("rounds must be positive")
    h, m = _split(n)
    x = QuantumRegister(n, "x")
    anc = AncillaRegister(h, "fa")
    qc = QuantumCircuit(x, anc, name=f"Feistel_{n}b_{rounds}r")

    wires = list(range(n))
    for r in range(rounds):
        left = [x[i] for i in wires[:h]]
        right = [x[i] for i in wires[h:]]
        key = feistel_round_key(r, h)
        _round_function(qc, right, anc, key, h, m)
        for i in range(h):
            qc.cx(anc[i], left[i])
        _round_function(qc, right, anc, key, h, m)   # uncompute
        wires = wires[h:] + wires[:h]
    return qc


def _phase_flip_on(qc: QuantumCircuit, qubits, target: int) -> None:
    """Multiply the amplitude of |target> by -1 over ``qubits`` (LSB = qubits[0])."""
    n = len(qubits)
    zeros = [qubits[i] for i in range(n) if not (target >> i) & 1]
    for q in zeros:
        qc.x(q)
    if n == 1:
        qc.z(qubits[0])
    else:
        qc.h(qubits[-1])
        qc.mcx([qubits[i] for i in range(n - 1)], qubits[-1])
        qc.h(qubits[-1])
    for q in zeros:
        qc.x(q)


def feistel_oracle(n: int, target: int, rounds: int = 4) -> QuantumCircuit:
    """Grover phase oracle marking every ``x`` with ``feistel_permute(x) == target``.

    Returns a circuit on ``n + n // 2`` qubits: the search register followed by
    the Feistel ancillas, which start and end in |0>.
    """
    if not 0 <= target < (1 << n):
        raise ValueError(f"target {target} out of range for {n} bits")
    perm = feistel_permutation(n, rounds)
    qc = QuantumCircuit(*perm.qregs, name=f"FeistelOracle_{n}b_{rounds}r_t{target}")
    x = qc.qregs[0]

    qc.compose(perm, qubits=qc.qubits, inplace=True)
    _phase_flip_on(qc, list(x), target)
    qc.compose(perm.inverse(), qubits=qc.qubits, inplace=True)
    return qc


def nonlinear_oracle(n: int, target: int, rounds: int = 4) -> QuantumCircuit:
    """Public entry point used by :class:`GroverNonLinearHash`."""
    return feistel_oracle(n, target, rounds=rounds)


def feistel_ancilla_count(n: int) -> int:
    return n // 2


# Smallest round count at which every output bit depends on every input bit
# (verified exhaustively in tests/test_feistel_oracle.py). Diffusion is not
# monotonic in the round count because the rotation stride and the golden-ratio
# key schedule interact, so the useful values are pinned per width instead of
# guessed. Anything not listed falls back to n // 2 + 2 rounds.
_FULL_DIFFUSION_ROUNDS = {3: 3, 4: 3, 8: 4}


def recommended_rounds(n: int) -> int:
    """Round count giving full bit-to-bit diffusion at the least circuit depth."""
    return _FULL_DIFFUSION_ROUNDS.get(n, n // 2 + 2)


if __name__ == "__main__":  # pragma: no cover - manual inspection
    for n in (3, 4, 8):
        oracle = nonlinear_oracle(n, target=1)
        image = {feistel_permute(x, n) for x in range(1 << n)}
        print(f"n={n:2d} qubits={oracle.num_qubits:3d} depth={oracle.depth():4d} "
              f"gates={len(oracle.data):4d} bijective={len(image) == 1 << n}")
