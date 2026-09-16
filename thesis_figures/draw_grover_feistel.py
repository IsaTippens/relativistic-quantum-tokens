import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qiskit.visualization.circuit._utils import _get_layered_instructions

from quantum_circuits.non_linear_oracle import feistel_permutation

OUT = Path(__file__).resolve().parent


def barrier_columns(qc, reverse_bits: bool = False):
    """Barrier columns and the total column count, using the drawer's layering.

    The matplotlib drawer places column ``i`` at x = i, so the returned indices
    can be used directly as data coordinates when annotating the figure.
    """
    _qc, _qubits, layers = _get_layered_instructions(qc, reverse_bits=reverse_bits)
    columns = []
    for index, layer in enumerate(layers):
        gates = layer[0] if isinstance(layer, tuple) else layer
        if any(gate.name == "barrier" for gate in gates):
            columns.append(index)
    return columns, len(layers)


def draw_grover_feistel():
    """Feistel permutation used inside the non-linear Grover oracle.

    Drawn at a 4-bit digest width with 3 rounds: register x holds the digest,
    register fa the two ancillas that carry F_r(R) and are cleared by replaying
    the same block. Only NOT, CNOT and Toffoli gates appear.

    Barriers separate the rounds and each round is named, so that the three
    rounds read as separate layers.
    """
    qc = feistel_permutation(4, rounds=3, barriers=True)
    fig = qc.draw(output="mpl", fold=-1)

    ax = fig.axes[0]
    barriers, columns = barrier_columns(qc)
    # Name each round over its own span rather than over the barrier that ends it.
    edges = [0] + barriers + [columns - 1]
    spans = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    top = ax.get_ylim()[1] + 1.4
    ax.set_ylim(top=top)
    for index, (start, end) in enumerate(spans, start=1):
        ax.text((start + end) / 2, top - 0.3, f"Round {index}",
                ha="center", va="top", fontsize=11)

    fig.savefig(OUT / "grover_feistel.png", dpi=300, bbox_inches="tight")
    print(f"wrote {OUT / 'grover_feistel.png'} ({len(spans)} rounds, {len(barriers)} barriers)")


if __name__ == "__main__":
    draw_grover_feistel()
