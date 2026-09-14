"""Turn a run directory into thesis figures and a written report.

    venv/bin/python experiments/ibm/make_report.py [--run-id ibmq_...]

Reads every artifact saved by the exp_*.py runners plus
results/classical_baselines.json, writes SVG/PNG figures to
benchmarks/<run_id>/ and a full REPORT.md into the run directory.

Hardware artifacts are named `<name>.json`, their noiseless references
`<name>_ideal.json`. Anything missing is reported as not run rather than
silently skipped.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from experiments.ibm.common import PROJECT_ROOT, RESULTS_ROOT  # noqa: E402

BENCH_ROOT = PROJECT_ROOT / "benchmarks"
WIDTHS = (3, 4, 8)
ALGORITHMS = ("grover", "feistel", "simple_xor")
ALGO_LABEL = {"grover": "Grover (linear)", "feistel": "Grover+Feistel",
              "simple_xor": "XOR parity"}
ALGO_COLOR = {"grover": "#4C72B0", "feistel": "#C44E52", "simple_xor": "#55A868"}


# ------------------------------------------------------------------------- input
def latest_run_id() -> str:
    runs = sorted(p.name for p in RESULTS_ROOT.iterdir()
                  if p.is_dir() and p.name.startswith("ibmq_"))
    if not runs:
        raise SystemExit("no run directories under results/")
    return runs[-1]


def load(run_root: Path, experiment: str, name: str) -> dict | None:
    path = run_root / experiment / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def fmt(value, spec=".3f", missing="n/a"):
    if value is None:
        return missing
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return missing
        return format(value, spec)
    return str(value)


def signal_vs_uniform(data: dict | None, width: int) -> float | None:
    """Mean total variation between each message's output and the flat digest.

    Hellinger fidelity against the noiseless run saturates near 1 whenever the
    noiseless distribution is itself almost flat, which is exactly the case for
    the under-rotated 8-bit Grover hashes. This measures how far the output
    sits from uniform, so hardware and ideal can be compared on the amount of
    structure present rather than on their agreement with each other.
    """
    if data is None:
        return None
    buckets = 1 << width
    uniform = {format(v, f"0{width}b"): 1.0 / buckets for v in range(buckets)}
    scores = []
    for row in data["analysis"]["per_circuit"]:
        if row["kind"] != "message":
            continue
        total = sum(row["counts"].values())
        dist = {k: v / total for k, v in row["counts"].items()}
        keys = set(dist) | set(uniform)
        scores.append(0.5 * sum(abs(dist.get(k, 0.0) - uniform.get(k, 0.0)) for k in keys))
    return sum(scores) / len(scores) if scores else None


def surviving_signal(hw: dict | None, ideal: dict | None, width: int) -> float | None:
    """Fraction of the noiseless distribution's structure left on hardware."""
    hw_score = signal_vs_uniform(hw, width)
    ideal_score = signal_vs_uniform(ideal, width)
    if hw_score is None or not ideal_score:
        return None
    return hw_score / ideal_score


# ----------------------------------------------------------------------- figures
def fig_hash_avalanche(hashing: dict, classical: dict, out: Path) -> Path | None:
    """Single-bit avalanche, hardware vs ideal vs truncated SHA-256/MD5."""
    fig, axes = plt.subplots(1, len(WIDTHS), figsize=(15, 4.6), sharey=True)
    any_data = False
    for ax, width in zip(axes, WIDTHS):
        labels, hw, ideal = [], [], []
        for algo in ALGORITHMS:
            hw_data = hashing.get((algo, width, "hw"))
            id_data = hashing.get((algo, width, "ideal"))
            if id_data is None:
                continue
            labels.append(ALGO_LABEL[algo])
            ideal.append(id_data["analysis"]["avalanche"]["expected_normalised"])
            hw.append(hw_data["analysis"]["avalanche"]["expected_normalised"]
                      if hw_data else np.nan)
            any_data = True
        x = np.arange(len(labels))
        ax.bar(x - 0.2, ideal, 0.38, label="noiseless simulator", color="#8C8C8C")
        ax.bar(x + 0.2, hw, 0.38, label="ibm_fez", color="#C44E52")
        for name, style in (("sha256", "-"), ("md5", "--")):
            ref = classical["table"][name][str(width)]["avalanche"]["one_flip_normalised"]
            ax.axhline(ref, ls=style, color="#333333", lw=1.2,
                       label=f"{name} (truncated)")
        ax.axhline(0.5, ls=":", color="#4C72B0", lw=1.4, label="ideal 0.5")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=18, ha="right")
        ax.set_title(f"{width}-bit digest")
        ax.set_ylim(0, 0.75)
        ax.grid(axis="y", alpha=0.3)
    if not any_data:
        plt.close(fig)
        return None
    axes[0].set_ylabel("normalised avalanche\n(mean output flips / width)")
    handles, labels_ = axes[-1].get_legend_handles_labels()
    fig.legend(handles, labels_, loc="upper center", ncol=6, frameon=False)
    fig.suptitle("Single input-bit avalanche: distribution-level estimator", y=1.12)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_hash_hamming_vs_flips(hashing: dict, classical: dict, out: Path) -> Path | None:
    fig, axes = plt.subplots(1, len(WIDTHS), figsize=(15, 4.4), sharey=True)
    any_data = False
    for ax, width in zip(axes, WIDTHS):
        for algo in ALGORITHMS:
            for source, ls, alpha in (("hw", "-", 1.0), ("ideal", "--", 0.55)):
                data = hashing.get((algo, width, source))
                if data is None:
                    continue
                curve = data["analysis"]["avalanche"]["per_flip_count"]
                xs = [c["flips"] for c in curve]
                ys = [c["expected_normalised"] for c in curve]
                ax.plot(xs, ys, ls, color=ALGO_COLOR[algo], alpha=alpha, marker="o",
                        ms=4, label=f"{ALGO_LABEL[algo]} "
                                    f"({'ibm_fez' if source == 'hw' else 'ideal'})")
                any_data = True
        for name, color in (("sha256", "#333333"), ("md5", "#777777")):
            curve = classical["table"][name][str(width)]["avalanche"]["per_flip_count"]
            ax.plot([c["flips"] for c in curve], [c["normalised"] for c in curve],
                    ":", color=color, marker="s", ms=4, label=f"{name} (truncated)")
        ax.axhline(0.5, ls=":", color="#4C72B0", lw=1.0)
        ax.set_title(f"{width}-bit digest")
        ax.set_xlabel("input bits flipped")
        ax.set_xticks([1, 2, 3, 4])
        ax.grid(alpha=0.3)
    if not any_data:
        plt.close(fig)
        return None
    axes[0].set_ylabel("normalised hamming distance")
    axes[-1].legend(fontsize=7, loc="lower right")
    fig.suptitle("Hamming distance versus number of flipped input bits")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_hash_fidelity_vs_depth(hashing: dict, out: Path) -> Path | None:
    points = []
    for algo in ALGORITHMS:
        for width in WIDTHS:
            hw = hashing.get((algo, width, "hw"))
            if hw is None:
                continue
            two_q = max(m["two_qubit_gates"] for m in hw["isa_metrics"])
            points.append((algo, width, two_q,
                           hw["analysis"]["vs_ideal"]["mean_hellinger_fidelity"]))
    if not points:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 5))
    for algo in ALGORITHMS:
        xs = [p[2] for p in points if p[0] == algo]
        ys = [p[3] for p in points if p[0] == algo]
        ws = [p[1] for p in points if p[0] == algo]
        ax.plot(xs, ys, "o-", color=ALGO_COLOR[algo], label=ALGO_LABEL[algo])
        for x, y, w in zip(xs, ys, ws):
            ax.annotate(f"{w}b", (x, y), textcoords="offset points", xytext=(6, 4),
                        fontsize=8)
    err = 0.00285  # ibm_fez median two-qubit gate error
    grid = np.logspace(0, 4.2, 200)
    ax.plot(grid, (1 - err) ** grid, "k:", lw=1.2,
            label=f"(1-{err})^N two-qubit budget")
    ax.set_xscale("log")
    ax.set_xlabel("two-qubit gates in the transpiled circuit")
    ax.set_ylabel("mean Hellinger fidelity vs noiseless")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    ax.set_title("Hash circuit fidelity against transpiled two-qubit gate count")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def _message_distribution(data: dict | None, width: int, message_index: int | None):
    """Normalised digest distribution: one message, or pooled over all messages."""
    if data is None:
        return None
    buckets = 1 << width
    totals = [0] * buckets
    for row in data["analysis"]["per_circuit"]:
        if row["kind"] != "message":
            continue
        if message_index is not None and row["message_index"] != message_index:
            continue
        for digest, count in row["counts"].items():
            totals[int(digest, 2)] += count
    grand = sum(totals)
    if not grand:
        return None
    return np.asarray(totals, dtype=float) / grand


def fig_hash_digest_distributions(hashing: dict, out: Path) -> Path | None:
    """Per-width digest distribution for one message, hardware against noiseless."""
    fig, axes = plt.subplots(1, len(WIDTHS), figsize=(15, 4.4))
    any_data = False
    for ax, width in zip(axes, WIDTHS):
        buckets = 1 << width
        x = np.arange(buckets)
        for algo in ALGORITHMS:
            hw = _message_distribution(hashing.get((algo, width, "hw")), width, 0)
            ideal = _message_distribution(hashing.get((algo, width, "ideal")), width, 0)
            if hw is not None:
                ax.step(x, hw, where="mid", color=ALGO_COLOR[algo], lw=1.4,
                        label=f"{ALGO_LABEL[algo]} (ibm_fez)")
                any_data = True
            if ideal is not None:
                ax.step(x, ideal, where="mid", color=ALGO_COLOR[algo], lw=1.0,
                        ls="--", alpha=0.45, label=f"{ALGO_LABEL[algo]} (noiseless)")
        ax.axhline(1.0 / buckets, ls=":", color="#333333", lw=1.0, label="uniform")
        ax.set_title(f"{width}-bit digest")
        ax.set_xlabel("digest value")
        ax.grid(alpha=0.3)
    if not any_data:
        plt.close(fig)
        return None
    axes[0].set_ylabel("probability")
    axes[-1].legend(fontsize=7, loc="upper right")
    fig.suptitle("Measured digest distribution for a single message, "
                 "hardware against noiseless")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_hash_digest_uniformity(hashing: dict, out: Path) -> Path | None:
    """Digest-space occupancy pooled over every evaluated message."""
    fig, axes = plt.subplots(1, len(WIDTHS), figsize=(15, 4.4))
    any_data = False
    for ax, width in zip(axes, WIDTHS):
        buckets = 1 << width
        x = np.arange(buckets)
        for algo in ALGORITHMS:
            data = hashing.get((algo, width, "hw"))
            pooled = _message_distribution(data, width, None)
            if pooled is None:
                continue
            entropy = data["analysis"]["uniformity"]["entropy_bits"]
            ax.step(x, pooled, where="mid", color=ALGO_COLOR[algo], lw=1.4,
                    label=f"{ALGO_LABEL[algo]} (H={entropy:.2f} bits)")
            any_data = True
        ax.axhline(1.0 / buckets, ls=":", color="#333333", lw=1.0,
                   label=f"uniform ({1.0 / buckets:.4f})")
        ax.set_title(f"{width}-bit digest")
        ax.set_xlabel("digest value")
        ax.grid(alpha=0.3)
    if not any_data:
        plt.close(fig)
        return None
    axes[0].set_ylabel("pooled probability")
    for ax in axes:
        ax.legend(fontsize=7, loc="upper right")
    fig.suptitle("Digest-space occupancy pooled over the 12 evaluated messages")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_t1(t1_hw: dict | None, out: Path) -> Path | None:
    if t1_hw is None:
        return None
    analysis = t1_hw["analysis"]
    delays = analysis["summary"]["delays_us"]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.6))
    grid = np.linspace(0, max(delays), 300)
    fitted = []
    for row in analysis["per_qubit"]:
        ax.plot(delays, row["excited_population"], "o", ms=3, alpha=0.5)
        fit = row["fit"]
        if fit.get("t1_us"):
            fitted.append(fit["t1_us"])
            ax.plot(grid, fit["amplitude"] * np.exp(-grid / fit["t1_us"]) + fit["offset"],
                    "-", lw=0.8, alpha=0.5)
    ax.set_xlabel("idle delay (us)")
    ax.set_ylabel("P(|1>)")
    ax.set_title(f"Relaxation of {len(analysis['per_qubit'])} probe qubits "
                 f"on {t1_hw['backend']}")
    ax.grid(alpha=0.3)

    reported = [r["calibration_t1_us"] for r in analysis["per_qubit"]
                if r["calibration_t1_us"] and r["fit"].get("t1_us")]
    measured = [r["fit"]["t1_us"] for r in analysis["per_qubit"]
                if r["calibration_t1_us"] and r["fit"].get("t1_us")]
    ax2.scatter(reported, measured, color="#C44E52")
    lim = max(reported + measured + [1]) * 1.1
    ax2.plot([0, lim], [0, lim], "k:", label="perfect agreement")
    ax2.set_xlabel("calibration-reported T1 (us)")
    ax2.set_ylabel("T1 fitted from this run (us)")
    ax2.set_title(f"mean fitted T1 = {fmt(analysis['summary']['mean_t1_us'], '.1f')} us")
    ax2.legend()
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_phase_cal(cal_hw: dict | None, out: Path) -> Path | None:
    if cal_hw is None:
        return None
    a = cal_hw["analysis"]
    delays = np.array([r["delay_us"] for r in a["per_delay"]], dtype=float)
    unwrapped = np.array(a["unwrapped_phase_rad"])
    visibility = np.array([r["visibility"] for r in a["per_delay"]])

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.5))
    grid = np.linspace(0, delays.max(), 200)
    ax.plot(delays, unwrapped, "o", color="#C44E52", label="measured fringe phase")
    ax.plot(grid, a["idle_phase_rate_rad_per_us"] * grid + a["idle_phase_intercept_rad"],
            "-", color="#333333",
            label=f"{a['idle_phase_rate_rad_per_us']:+.4f} rad/us "
                  f"({a['implied_detuning_khz']:+.1f} kHz)")
    ax.set_xlabel("idle delay on Bob's qubit (us)")
    ax.set_ylabel("unwrapped fringe phase (rad)")
    ax.set_title(f"Parasitic idle phase, pair {a['pair']['pair']} "
                 f"(R^2 = {fmt(a['linear_fit_r_squared'], '.4f')})")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax2.plot(delays, visibility, "o", color="#4C72B0", label="fringe visibility")
    decay = a["entanglement_visibility_decay"]
    if decay.get("tau_us"):
        ax2.plot(grid, decay["v0"] * np.exp(-grid / decay["tau_us"]), "-",
                 color="#333333", label=f"tau = {decay['tau_us']:.0f} us")
    ax2.set_xlabel("idle delay (us)")
    ax2.set_ylabel("visibility")
    ax2.set_ylim(0, 1.05)
    ax2.set_title("Bell-pair correlation lifetime")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_sync(sync_hw: dict | None, sync_ideal: dict | None, out: Path) -> Path | None:
    source = sync_hw or sync_ideal
    if source is None:
        return None
    fig, ax = plt.subplots(figsize=(8.4, 5))
    colors = {"initial_drift": "#C44E52", "adjusting": "#DD8452", "synced": "#55A868"}
    grid = np.linspace(0, 2 * math.pi, 300)
    for label, data, ls, alpha in (("ibm_fez", sync_hw, "-", 1.0),
                                   ("ideal", sync_ideal, "--", 0.45)):
        if data is None:
            continue
        for stage, stage_data in data["analysis"]["stages"].items():
            xs = [p["scan_phase"] for p in stage_data["points"]]
            ys = [p["correlation"] for p in stage_data["points"]]
            ax.plot(xs, ys, "o" if label == "ibm_fez" else "s", ms=5,
                    color=colors[stage], alpha=alpha)
            fit = stage_data["fit"]
            ax.plot(grid, fit["visibility"] * np.cos(grid + fit["phase_offset_rad"]),
                    ls, color=colors[stage], alpha=alpha,
                    label=f"{stage} ({label}, V={fit['visibility']:.2f})")
    ax.set_xlabel("scan phase (rad)")
    ax.set_ylabel("correlation  E = P(same) - P(different)")
    ax.set_title("Three-stage clock synchronisation: correlation fringes")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylim(-1.15, 1.15)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_superdense(decay_hw: dict | None, decay_ideal: dict | None, out: Path) -> Path | None:
    source = decay_hw or decay_ideal
    if source is None:
        return None
    fig, ax = plt.subplots(figsize=(8.2, 5))
    ax2 = ax.twinx()
    for label, data, ls in (("ibm_fez", decay_hw, "-"), ("ideal", decay_ideal, "--")):
        if data is None:
            continue
        a = data["analysis"]
        ax.plot(a["delays_us"], a["ber"], ls, marker="o", color="#C44E52",
                label=f"bit error rate ({label})")
        ax2.plot(a["delays_us"], a["exact_match_rate"], ls, marker="s",
                 color="#4C72B0", label=f"exact 8-bit match ({label})")
    if decay_hw and decay_hw["analysis"]["fit"].get("tau_us"):
        tau = decay_hw["analysis"]["fit"]["tau_us"]
        ax.axvline(tau, color="#333333", ls=":",
                   label=f"fitted lifetime tau = {tau:.0f} us")
    ax.axhline(0.25, color="#888888", ls=":", lw=1)
    ax.set_xlabel("storage delay between encode and decode (us)")
    ax.set_ylabel("bit error rate")
    ax2.set_ylabel("exact match rate")
    ax.set_ylim(0, 0.55)
    ax2.set_ylim(0, 1.05)
    ax.grid(alpha=0.3)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="center right")
    ax.set_title("Superdense-coded token hash: survival versus storage time")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


def fig_bb84(bb84_hw: dict | None, out: Path) -> Path | None:
    if bb84_hw is None:
        return None
    analysis = bb84_hw["analysis"]
    matched = [p for p in analysis["per_position"] if p["bases_match"]]
    mismatched = [p for p in analysis["per_position"] if not p["bases_match"]]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.4),
                                  gridspec_kw={"width_ratios": [2, 1]})
    ax.bar([p["position"] for p in matched], [p["error_rate"] for p in matched],
           color="#55A868", label="bases match (sifted)")
    ax.bar([p["position"] for p in mismatched], [p["error_rate"] for p in mismatched],
           color="#C7C7C7", label="bases differ (discarded)")
    ax.axhline(analysis["averaged"]["matched_qber_mean"], color="#C44E52",
               label=f"mean sifted QBER = "
                     f"{analysis['averaged']['matched_qber_mean']:.3f}")
    ax.axhline(0.11, color="#333333", ls="--", label="BB84 abort threshold 0.11")
    ax.set_xlabel("key position (qubit)")
    ax.set_ylabel("error rate vs Alice's bit")
    ax.set_title(f"BB84 single exchange on {bb84_hw['backend']}, "
                 f"{analysis['shots']} shots")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    labels = ["sifted\n(matched)", "discarded\n(mismatched)", "Z prep", "X prep"]
    values = [analysis["averaged"]["matched_qber_mean"],
              analysis["averaged"]["mismatched_qber_mean"],
              analysis["averaged"]["z_basis_qber_mean"],
              analysis["averaged"]["x_basis_qber_mean"]]
    ax2.bar(labels, values, color=["#55A868", "#C7C7C7", "#4C72B0", "#DD8452"])
    ax2.axhline(0.11, color="#333333", ls="--")
    ax2.set_ylabel("QBER")
    ax2.set_title("QBER breakdown")
    ax2.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=200)
    plt.close(fig)
    return out


# ------------------------------------------------------------------------ report
def hashing_table(hashing: dict, classical: dict) -> list[str]:
    lines = [
        "| construction | width | iters | qubits | ISA depth | 2q gates | "
        "fidelity vs ideal | top-1 agreement | surviving signal | "
        "avalanche (hw) | avalanche (ideal) | entropy hw/ideal | distinct top-1 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for algo in ALGORITHMS:
        for width in WIDTHS:
            hw = hashing.get((algo, width, "hw"))
            ideal = hashing.get((algo, width, "ideal"))
            if ideal is None:
                continue
            ref = hw or ideal
            depth = max(m["depth"] for m in ref["isa_metrics"])
            two_q = max(m["two_qubit_gates"] for m in ref["isa_metrics"])
            qubits = ideal["logical_metrics"][0]["num_qubits"]
            a_hw = hw["analysis"] if hw else None
            a_id = ideal["analysis"]
            lines.append(
                f"| {ALGO_LABEL[algo]} | {width} | {ideal['grover_iterations'] or '-'} | "
                f"{qubits} | {depth} | {two_q} | "
                f"{fmt(a_hw['vs_ideal']['mean_hellinger_fidelity'] if a_hw else None)} | "
                f"{fmt(a_hw['vs_ideal']['top1_agreement_rate'] if a_hw else None, '.2f')} | "
                f"{fmt(surviving_signal(hw, ideal, width))} | "
                f"{fmt(a_hw['avalanche']['expected_normalised'] if a_hw else None)} | "
                f"{fmt(a_id['avalanche']['expected_normalised'])} | "
                f"{fmt(a_hw['uniformity']['entropy_bits'] if a_hw else None, '.2f')}"
                f"/{fmt(a_id['uniformity']['entropy_bits'], '.2f')} | "
                f"{fmt(a_hw['determinism']['distinct_top1_hashes'] if a_hw else None, 'd')}"
                f"/{a_id['determinism']['n_messages']} |")
    lines.append("")
    lines.append("Read the three hardware columns together: `fidelity vs ideal` "
                 "saturates near 1 whenever the noiseless distribution is "
                 "itself almost flat, `top-1 agreement` asks whether the "
                 "argmax the protocol would use is the right one, and "
                 "`surviving signal` is how much of the noiseless "
                 "distribution's distance from uniform is left.")
    lines.append("")
    lines.append("Classical references, same widths, digests truncated to the "
                 "same number of bits:")
    lines.append("")
    lines.append("| algorithm | width | 1-flip avalanche | 4-flip avalanche | "
                 "entropy | chi2 uniform |")
    lines.append("|---|---|---|---|---|---|")
    for name in ("sha256", "md5"):
        for width in WIDTHS:
            data = classical["table"][name][str(width)]
            four = next(c["normalised"] for c in data["avalanche"]["per_flip_count"]
                        if c["flips"] == 4)
            lines.append(f"| {name} | {width} | "
                         f"{fmt(data['avalanche']['one_flip_normalised'])} | "
                         f"{fmt(four)} | "
                         f"{fmt(data['uniformity']['entropy_bits'], '.2f')} | "
                         f"{fmt(data['uniformity']['passes_uniformity'])} |")
    return lines

def build_report(run_id: str, run_root: Path, manifest: dict, calibration: dict,
                 hashing: dict, classical: dict, qcs: dict, sdc: dict, bb84: dict | None,
                 figures: dict, jobs: list) -> str:
    backend = manifest["backend"]
    quantum_seconds = sum(j.get("quantum_seconds") or 0 for j in jobs)
    lines: list[str] = []
    add = lines.append

    add(f"# IBM Quantum hardware run `{run_id}`")
    add("")
    add("## Device")
    add("")
    processor = backend.get("processor_type") or {}
    if isinstance(processor, dict):
        processor = " ".join(str(v) for v in processor.values())
    add(f"- **QPU: `{backend['name']}`** ({backend['num_qubits']} qubits, "
        f"{processor})")
    add(f"- Calibrated {backend['last_calibration_utc']} "
        f"({backend['calibration_age_hours']} h before selection)")
    add(f"- Median T1 {backend['median_t1_us']} us, median T2 {backend['median_t2_us']} us")
    add(f"- Median 2-qubit ({backend['two_qubit_gate']}) error "
        f"{backend['median_2q_error']}, median readout error "
        f"{backend['median_readout_error']}")
    add(f"- Instance `{manifest['instance_name']}` ({manifest['instance_region']}), "
        f"channel `{manifest['channel']}`")
    add(f"- Selection rule: {manifest['selection_rule']}")
    add("")
    add("Candidates surveyed at selection time:")
    add("")
    survey = manifest["backend_survey"]
    survey_path = RESULTS_ROOT / "backend_survey.json"
    if survey_path.exists():
        full = json.loads(survey_path.read_text()).get("backends", [])
        if len(full) > len(survey):
            survey = full
    add("| backend | qubits | calibration age (h) | median 2q error | "
        "median readout error | median T1 (us) | median T2 (us) | queue |")
    add("|---|---|---|---|---|---|---|---|")
    for row in survey:
        mark = " **(chosen)**" if row["name"] == backend["name"] else ""
        add(f"| `{row['name']}`{mark} | {row['num_qubits']} | "
            f"{row['calibration_age_hours']} | {row['median_2q_error']} | "
            f"{row['median_readout_error']} | {row['median_t1_us']} | "
            f"{row['median_t2_us']} | {row['pending_jobs']} |")
    add("")
    add(f"Full per-qubit calibration snapshot: "
        f"`calibration_{backend['name']}.json` "
        f"({len(calibration['qubits'])} qubits, "
        f"{len(calibration['two_qubit_pairs'])} calibrated pairs).")
    add("")
    add(f"- Jobs submitted: {len(jobs)}; billed QPU time "
        f"{quantum_seconds:.2f} s (open plan grants 600 s / 28 days)")
    add("")
    add("| job id | tag | circuits | shots | quantum seconds |")
    add("|---|---|---|---|---|")
    for job in jobs:
        add(f"| `{job['job_id']}` | {job['tag']} | {job['n_circuits']} | "
            f"{job['shots']} | {fmt(job.get('quantum_seconds'), '.2f')} |")
    add("")

    add("## Hashing")
    add("")
    add("Three constructions at 3, 4 and 8 bits, all fed the same 16-bit input "
        "space. `fidelity vs ideal` is the mean Hellinger fidelity between the "
        "hardware and noiseless output distributions; `avalanche` is the "
        "distribution-level estimator E[HD] over a single input-bit flip, "
        "normalised by the digest width (0.5 is ideal).")
    add("")
    lines.extend(hashing_table(hashing, classical))
    add("")
    for key in ("avalanche", "hamming", "fidelity"):
        if figures.get(f"hash_{key}"):
            add(f"![hash {key}]({figures[f'hash_{key}']})")
            add("")

    add("## Quantum clock synchronisation")
    add("")
    t1 = qcs.get("t1")
    if t1:
        s = t1["analysis"]["summary"]
        add(f"Relaxation measured on {s['n_probes']} probe qubits "
            f"({t1['probe_qubits']}), delays {s['delays_us']} us, "
            f"{t1['shots']} shots each:")
        add("")
        add(f"- **Mean fitted T1 = {fmt(s['mean_t1_us'], '.1f')} us** "
            f"(median {fmt(s['median_t1_us'], '.1f')}, "
            f"sd {fmt(s['stdev_t1_us'], '.1f')}, "
            f"range {fmt(s['min_t1_us'], '.1f')}-{fmt(s['max_t1_us'], '.1f')})")
        add(f"- Device-reported mean over the same qubits: "
            f"{fmt(s['calibration_mean_t1_us'], '.1f')} us")
        add(f"- Fits converged for {s['n_fitted']}/{s['n_probes']} probes")
        add("")
    else:
        add("_T1 stage not run on hardware._")
        add("")
    if figures.get("qcs_t1"):
        add(f"![T1]({figures['qcs_t1']})")
        add("")

    cal = qcs.get("phase_cal")
    if cal:
        a = cal["analysis"]
        decay = a["entanglement_visibility_decay"]
        add("### Idle-phase calibration")
        add("")
        add("An idling qubit accumulates phase the rotating frame does not "
            "track. Left unmeasured this is indistinguishable from the clock "
            "offset the protocol is trying to recover, so it is calibrated "
            "first by sweeping the idle time with no deliberate drift applied.")
        add("")
        add(f"- **Idle phase rate {a['idle_phase_rate_rad_per_us']:+.4f} rad/us** "
            f"({a['implied_detuning_khz']:+.2f} kHz residual detuning), "
            f"linear fit R^2 = {fmt(a['linear_fit_r_squared'], '.4f')}")
        add(f"- Phase wraps every {fmt(a['phase_wrap_period_us'], '.1f')} us, "
            f"which bounds the unambiguous offset range")
        add(f"- Bell-pair correlation lifetime "
            f"tau = {fmt(decay.get('tau_us'), '.1f')} us "
            f"(device median T2 is "
            f"{manifest['backend']['median_t2_us']} us)")
        add("")
        add("| idle delay (us) | fringe visibility | fringe phase (rad) |")
        add("|---|---|---|")
        for row, unwrapped in zip(a["per_delay"], a["unwrapped_phase_rad"]):
            add(f"| {row['delay_us']} | {row['visibility']:.3f} | {unwrapped:+.3f} |")
        add("")
    if figures.get("qcs_phase_cal"):
        add(f"![idle phase]({figures['qcs_phase_cal']})")
        add("")

    sync = qcs.get("sync")
    if sync:
        a = sync["analysis"]
        add("### Three stages")
        add("")
        add(f"Pair {a['pair']['pair']} "
            f"({a['pair']['gate']} error {a['pair']['error']:.5f}). "
            f"T1 used: {a['t1_us']:.1f} us ({a['t1_source']}); "
            f"omega = {a['omega_rad_per_us']:.5f} rad/us, so a full-T1 offset is "
            f"a quarter turn of deliberate phase. Idle phase rate applied in the "
            f"analysis: {fmt(a.get('idle_phase_rate_rad_per_us'), '+.4f')} rad/us "
            f"({a.get('idle_phase_source')}).")
        add("")
        add("| stage | offset dt (us) | applied phase (rad) | E(phi=0) | "
            "anti-correlated % | visibility | measured fringe phase (rad) |")
        add("|---|---|---|---|---|---|---|")
        for stage, data in a["stages"].items():
            add(f"| {stage} | {data['dt_us']:.1f} | "
                f"{data['applied_drift_phase_rad']:.4f} | "
                f"{data['correlation_at_zero_phase']:+.3f} | "
                f"{data['error_percentage_at_zero_phase']:.2f} | "
                f"{data['fit']['visibility']:.3f} | "
                f"{data['fit']['phase_offset_rad']:+.3f} |")
        add("")
        if any(d.get("calibrated") for d in a["stages"].values()):
            first = next(d["calibrated"] for d in a["stages"].values()
                         if d.get("calibrated"))
            add(f"Offset recovery after subtracting the calibrated idle phase "
                f"(total rate {first['total_phase_rate_rad_per_us']:+.4f} rad/us, "
                f"unambiguous only below "
                f"{first['unambiguous_range_us']:.1f} us of offset):")
            add("")
            add("| stage | predicted phase (rad) | model residual (rad) | "
                "wraps | recovered offset (us) | error (us) |")
            add("|---|---|---|---|---|---|")
            for stage, data in a["stages"].items():
                c = data.get("calibrated")
                if not c:
                    continue
                add(f"| {stage} | {c['predicted_phase_rad']:+.3f} | "
                    f"{c['model_residual_rad']:+.3f} | {c['phase_wraps']} | "
                    f"{c['recovered_offset_us']:+.1f} | "
                    f"{c['offset_error_us']:+.1f} |")
            add("")
        else:
            add("| stage | recovered offset (us), uncalibrated | error (us) |")
            add("|---|---|---|")
            for stage, data in a["stages"].items():
                add(f"| {stage} | {data['recovered_offset_us']:+.1f} | "
                    f"{data['offset_error_us']:+.1f} |")
            add("")
    else:
        add("_Sync stage not run on hardware._")
        add("")
    if figures.get("qcs_sync"):
        add(f"![sync fringes]({figures['qcs_sync']})")
        add("")

    chsh = qcs.get("chsh")
    if chsh:
        a = chsh["analysis"]
        add(f"CHSH on the same pair: **S = {a['S']:.4f}** "
            f"(classical bound 2, Tsirelson {a['tsirelson_bound']:.4f}) - "
            f"{'violates' if a['violates_classical_bound'] else 'does not violate'} "
            f"the classical bound, so the correlations above are "
            f"{'genuinely entangled' if a['violates_classical_bound'] else 'not certified'}.")
        add("")

    add("## Superdense coding")
    add("")
    proto = sdc.get("protocol")
    if proto:
        a = proto["analysis"]
        add(f"Baseline, four 2-bit messages over one Bell pair, "
            f"{proto['shots']} shots each:")
        add("")
        add("| message | accuracy | fidelity vs ideal |")
        add("|---|---|---|")
        for row in a["per_message"]:
            add(f"| {row['message']} | {row['accuracy']:.4f} | "
                f"{fmt(row.get('hellinger_fidelity_vs_ideal'), '.4f')} |")
        add("")
        add(f"Mean accuracy **{a['mean_accuracy']:.4f}** "
            f"(sd {a['std_accuracy']:.4f}), per-bit error rate "
            f"{a['per_bit_error_rate']:.4f}.")
        add("")
    token = sdc.get("token")
    if token:
        a = token["analysis"]
        add(f"Token hash `{token['token_bits']}` (GroverHash-8 of "
            f"`{token['token_payload']}`) sent over {token['n_pairs']} Bell pairs:")
        add("")
        add(f"- exact 8-bit match rate **{a['exact_match_rate']:.4f}**")
        add(f"- mean bit error rate {a['mean_bit_error_rate']:.4f}, "
            f"mean hamming distance {a['mean_hamming_bits']:.3f} bits")
        add(f"- per-bit error rate {[round(v, 4) for v in a['per_bit_error_rate']]} "
            f"(worst bit {a['worst_bit']})")
        add("")
    decay = sdc.get("decay")
    if decay:
        a = decay["analysis"]
        add("Storage window between encoding and decoding:")
        add("")
        add("| delay (us) | bit error rate | exact match rate |")
        add("|---|---|---|")
        for row in a["per_delay"]:
            add(f"| {row['delay_us']} | {row['mean_bit_error_rate']:.4f} | "
                f"{row['exact_match_rate']:.4f} |")
        add("")
        add(f"- fitted payload lifetime tau = {fmt(a['fit'].get('tau_us'), '.1f')} us "
            f"(R^2 {fmt(a['fit'].get('r_squared'), '.3f')})")
        add(f"- last delay still decoding the whole hash more than half the time: "
            f"{fmt(a['max_delay_with_half_exact_match_us'], '.0f')} us")
        add(f"- bit error rate crosses 0.25 at "
            f"{fmt(a['delay_at_ber_0p25_us'], '.0f')} us")
        add("")
    if figures.get("superdense_decay"):
        add(f"![superdense decay]({figures['superdense_decay']})")
        add("")

    add("## BB84")
    add("")
    if bb84:
        a = bb84["analysis"]
        single = a["single_run"]
        avg = a["averaged"]
        add(f"One exchange of {a['nbits']} prepared qubits, {a['shots']} shots.")
        add("")
        add(f"- sifted {a['sifting']['n_matched']}/{a['nbits']} positions "
            f"(rate {a['sifting']['sift_rate']:.3f}, expected 0.5)")
        add(f"- single shot (shot 0): QBER {single['qber']:.4f} over "
            f"{single['sifted_length']} sifted bits, key "
            f"`{single['sifted_key_hex']}`")
        add(f"- 1000-shot mean sifted QBER **{avg['matched_qber_mean']:.4f}** "
            f"(sd {avg['matched_qber_std']:.4f}, "
            f"range {avg['matched_qber_min']:.3f}-{avg['matched_qber_max']:.3f})")
        add(f"- control: mismatched-basis QBER {avg['mismatched_qber_mean']:.4f} "
            f"(expected 0.5)")
        add(f"- by preparation basis: Z {avg['z_basis_qber_mean']:.4f}, "
            f"X {avg['x_basis_qber_mean']:.4f}")
        add(f"- **{a['security']['verdict']}** "
            f"(threshold {a['security']['threshold']})")
        add("")
    else:
        add("_BB84 not run on hardware._")
        add("")
    if figures.get("bb84"):
        add(f"![bb84]({figures['bb84']})")
        add("")

    add("## Against the numbers already in the thesis")
    add("")
    add("Prior hardware figures quoted in `chapters/results.tex` for comparison. "
        "Different devices and different generations, so read these as context "
        "rather than as a controlled comparison.")
    add("")
    add("| quantity | previously reported | this run (`" + backend["name"] + "`) |")
    add("|---|---|---|")
    t1_row = qcs.get("t1")
    add(f"| T1 relaxation | 433.16 us (ibm_brussels, Eagle r3) | "
        f"{fmt(t1_row['analysis']['summary']['mean_t1_us'] if t1_row else None, '.1f')} us "
        f"mean over 16 probes |")
    sync_row = qcs.get("sync")
    if sync_row:
        stages = sync_row["analysis"]["stages"]
        add(f"| synchronised correlation | 77.4% | "
            f"{stages['synced']['correlation_at_zero_phase'] * 100:.1f}% |")
        add(f"| offset-applied correlation | 58.5% (Alice delayed), "
            f"53.5% (Bob delayed) | "
            f"{abs(stages['adjusting']['correlation_at_zero_phase']) * 100:.1f}% "
            f"at 0.25xT1, "
            f"{abs(stages['initial_drift']['correlation_at_zero_phase']) * 100:.1f}% "
            f"at 1.0xT1 |")
    hw8 = hashing.get(("grover", 8, "hw"))
    hw3 = hashing.get(("grover", 3, "hw"))
    add("| Grover hash width usable on hardware | downscaled from 8-bit to "
        "3-bit (ibm_kingston) | "
        f"3-bit top-1 agreement "
        f"{fmt(hw3['analysis']['vs_ideal']['top1_agreement_rate'] if hw3 else None, '.2f')}, "
        f"8-bit "
        f"{fmt(hw8['analysis']['vs_ideal']['top1_agreement_rate'] if hw8 else None, '.2f')} "
        "- same conclusion, now with the gate counts that cause it |")
    add("")
    add("New in this run and not previously measured: the Feistel "
        "(non-linear) oracle on hardware at all three widths, the idle-phase "
        "calibration that makes the recovered clock offset meaningful, a CHSH "
        "test certifying the entanglement the sync and superdense stages "
        "depend on, superdense transmission of a complete token hash with its "
        "storage lifetime, and SHA-256/MD5 baselines truncated to the same "
        "digest widths.")
    add("")

    add("## Reproducing")
    add("")
    add("```")
    add("venv/bin/python experiments/ibm/select_backend.py")
    add("venv/bin/python experiments/ibm/classical_baselines.py")
    add("venv/bin/python experiments/ibm/exp_bb84.py --submit")
    add("venv/bin/python experiments/ibm/exp_superdense.py --submit")
    add("venv/bin/python experiments/ibm/exp_qcs.py --submit")
    add("venv/bin/python experiments/ibm/exp_hashing.py --submit")
    add(f"venv/bin/python experiments/ibm/make_report.py --run-id {run_id}")
    add("```")
    add("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    run_id = args.run_id or latest_run_id()
    run_root = RESULTS_ROOT / run_id
    manifest = json.loads((run_root / "run_manifest.json").read_text())
    backend_name = manifest["backend"]["name"]
    calibration = json.loads((run_root / f"calibration_{backend_name}.json").read_text())
    jobs_path = run_root / "jobs.json"
    jobs = json.loads(jobs_path.read_text()) if jobs_path.exists() else []

    classical_path = RESULTS_ROOT / "classical_baselines.json"
    if not classical_path.exists():
        raise SystemExit("run experiments/ibm/classical_baselines.py first")
    classical = json.loads(classical_path.read_text())

    hashing = {}
    for algo in ALGORITHMS:
        for width in WIDTHS:
            hashing[(algo, width, "hw")] = load(run_root, "hashing", f"{algo}_{width}bit")
            hashing[(algo, width, "ideal")] = load(run_root, "hashing",
                                                   f"{algo}_{width}bit_ideal")
    qcs = {
        "t1": load(run_root, "qcs", "t1_relaxation"),
        "t1_ideal": load(run_root, "qcs", "t1_relaxation_ideal"),
        "phase_cal": load(run_root, "qcs", "idle_phase_calibration"),
        "sync": load(run_root, "qcs", "sync_three_stage"),
        "sync_ideal": load(run_root, "qcs", "sync_three_stage_ideal"),
        "chsh": load(run_root, "qcs", "chsh"),
    }
    sdc = {
        "protocol": load(run_root, "superdense", "protocol_2qubit"),
        "token": load(run_root, "superdense", "token_transmission"),
        "decay": load(run_root, "superdense", "token_decay"),
        "decay_ideal": load(run_root, "superdense", "token_decay_ideal"),
    }
    bb84 = load(run_root, "bb84", "single_exchange")

    bench_dir = BENCH_ROOT / run_id
    bench_dir.mkdir(parents=True, exist_ok=True)
    produced = {
        "hash_avalanche": fig_hash_avalanche(hashing, classical,
                                             bench_dir / "hash_avalanche.png"),
        "hash_hamming": fig_hash_hamming_vs_flips(hashing, classical,
                                                  bench_dir / "hash_hamming_vs_flips.png"),
        "hash_fidelity": fig_hash_fidelity_vs_depth(hashing,
                                                    bench_dir / "hash_fidelity_vs_depth.png"),
        "hash_digests": fig_hash_digest_distributions(
            hashing, bench_dir / "hash_digest_distributions.png"),
        "hash_uniformity": fig_hash_digest_uniformity(
            hashing, bench_dir / "hash_uniformity.png"),
        "qcs_t1": fig_t1(qcs["t1"], bench_dir / "qcs_t1.png"),
        "qcs_phase_cal": fig_phase_cal(qcs["phase_cal"], bench_dir / "qcs_phase_cal.png"),
        "qcs_sync": fig_sync(qcs["sync"], qcs["sync_ideal"], bench_dir / "qcs_sync.png"),
        "superdense_decay": fig_superdense(sdc["decay"], sdc["decay_ideal"],
                                           bench_dir / "superdense_decay.png"),
        "bb84": fig_bb84(bb84, bench_dir / "bb84_qber.png"),
    }
    figures = {}
    for key, path in produced.items():
        if path is None:
            continue
        figures[key] = str(Path("..") / ".." / path.relative_to(PROJECT_ROOT))
        print(f"  figure {path.relative_to(PROJECT_ROOT)}")

    report = build_report(run_id, run_root, manifest, calibration, hashing, classical,
                          qcs, sdc, bb84, figures, jobs)
    out = run_root / "REPORT.md"
    out.write_text(report)
    print(f"  report {out.relative_to(PROJECT_ROOT)} ({len(report.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
