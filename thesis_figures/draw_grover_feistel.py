import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantum_circuits.non_linear_oracle import feistel_permutation


def draw_grover_feistel():
    """Feistel permutation used inside the non-linear Grover oracle.

    Drawn at a 4-bit digest width with 3 rounds: register x holds the digest,
    register fa the two ancillas that carry F_r(R) and are cleared by replaying
    the same block. Only NOT, CNOT and Toffoli gates appear.
    """
    qc = feistel_permutation(4, rounds=3)
    qc.draw(output='mpl', fold=-1, filename='thesis_figures/grover_feistel.png')


if __name__ == "__main__":
    draw_grover_feistel()
