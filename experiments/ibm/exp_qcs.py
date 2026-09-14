"""Quantum clock synchronisation on hardware: T1, three-stage sync, CHSH.

    venv/bin/python experiments/ibm/exp_qcs.py                 # dry run
    venv/bin/python experiments/ibm/exp_qcs.py --submit        # ibm_fez

Stages
  t1    how long a qubit takes to relax. |1> is prepared on 16 spread-out
        probe qubits, they idle for a swept delay, then all are measured.
        A*exp(-t/T1)+c is fitted per probe and compared with the value the
        device reports in its own calibration.
  sync  the three-stage clock-synchronisation experiment from the protocol
        prototype (~/dev/uni/projects/code/time_sync). A Bell pair is shared;
        Bob's residual clock offset dt shows up both as an idle delay on his
        qubit and as the phase omega*dt it accumulates. Scanning a probe phase
        traces the correlation fringe, whose visibility measures how much
        entanglement survived and whose phase recovers the offset.
            initial_drift  dt = 1.0 * T1      (uncorrected)
            adjusting      dt = 0.25 * T1     (correction applied, drift left)
            synced         dt = 0             (corrected)
        omega is fixed by omega * (1.0 * T1) = pi/2, so the uncorrected drift
        is a quarter turn of phase error: large enough to see, small enough to
        stay inside one unambiguous fringe.
  chsh  Bell inequality on the same pair. The sync protocol's correlations are
        only meaningful if the pair is genuinely entangled, so S > 2 is the
        precondition for reading anything into the sync numbers.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister  # noqa: E402

from experiments.ibm.common import (  # noqa: E402
    assert_budget,
    circuit_metrics,
    estimate_qpu_seconds,
    mean_std,
    open_run,
    run_ideal,
    run_sampler,
    transpile_isa,
)

EXPERIMENT = "qcs"
PROBE_STRIDE = 9          # 16 probes across a 156-qubit device
N_PROBES = 16
T1_DELAYS_US = (0, 10, 25, 50, 75, 100, 150, 200, 275, 350, 450, 600)
T1_SHOTS = 512
SCAN_PHASES = 8
SYNC_STAGES = {"initial_drift": 1.0, "adjusting": 0.25, "synced": 0.0}
DRIFT_PHASE_AT_FULL_T1 = math.pi / 2
# Idle-phase calibration. On hardware an idling qubit accumulates phase that
# the rotating frame does not track (residual detuning plus ZZ shift from
# neighbours). The first hardware run showed ~0.11 rad/us on this pair, eight
# times the deliberate drift rate, which wraps 2*pi about every 56 us and makes
# the recovered clock offset ambiguous. This stage measures the rate so the
# sync analysis can subtract it and state its unambiguous range.
PHASE_CAL_DELAYS_US = (0, 10, 20, 30, 45, 60, 90, 120)
PHASE_CAL_PHASES = 4


def fmt_opt(value, spec: str = ".4f") -> str:
    """Format a value that may be None or NaN."""
    if value is None:
        return "n/a"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "n/a"
    return format(value, spec)


# ------------------------------------------------------------------------- setup
def probe_qubits(backend) -> list[int]:
    qubits = list(range(0, backend.num_qubits, PROBE_STRIDE))[:N_PROBES]
    if len(qubits) < N_PROBES:
        qubits = list(range(N_PROBES))
    return qubits


def best_pair(backend) -> dict:
    """Lowest-error coupled pair; the sync and CHSH stages are pinned to it."""
    target = backend.target
    gate = next(g for g in ("cz", "ecr", "cx") if g in target.operation_names)
    best = None
    for qargs, inst in target[gate].items():
        if not qargs or len(qargs) != 2 or inst is None or inst.error is None:
            continue
        if best is None or inst.error < best["error"]:
            best = {"pair": [int(qargs[0]), int(qargs[1])], "gate": gate,
                    "error": float(inst.error), "duration_s": inst.duration}
    if best is None:
        raise RuntimeError("no calibrated two-qubit pair on this backend")
    return best


def calibration_t1_us(ctx, qubits: list[int]) -> dict:
    path = ctx.root / f"calibration_{ctx.backend_name}.json"
    data = json.loads(path.read_text())
    out = {}
    for q in qubits:
        entry = data["qubits"].get(str(q), {})
        t1 = entry.get("t1_s")
        out[str(q)] = t1 * 1e6 if t1 else None
    return out


def resolve_t1_us(ctx, args) -> tuple[float, str]:
    """Measured T1 if this run already produced one, else the device value."""
    if args.t1_us:
        return args.t1_us, "command line"
    measured = ctx.root / EXPERIMENT / "t1_relaxation.json"
    if measured.exists():
        data = json.loads(measured.read_text())
        value = data["analysis"]["summary"]["mean_t1_us"]
        if value:
            return float(value), f"measured on {ctx.backend_name} (t1_relaxation.json)"
    cal = calibration_t1_us(ctx, probe_qubits(ctx.backend))
    values = [v for v in cal.values() if v]
    return statistics.median(values), f"{ctx.backend_name} calibration median"


# ---------------------------------------------------------------------- circuits
def t1_circuits(probes: list[int]) -> list[QuantumCircuit]:
    circuits = []
    for delay_us in T1_DELAYS_US:
        qr = QuantumRegister(len(probes), "q")
        cr = ClassicalRegister(len(probes), "c")
        qc = QuantumCircuit(qr, cr, name=f"t1_{delay_us}us")
        qc.x(qr)
        if delay_us:
            qc.barrier()
            qc.delay(delay_us, qr, unit="us")
            qc.barrier()
        qc.measure(qr, cr)
        circuits.append(qc)
    return circuits


def sync_circuit(stage: str, dt_us: float, omega_rad_per_us: float,
                 scan_phase: float) -> QuantumCircuit:
    qr = QuantumRegister(2, "q")
    cr = ClassicalRegister(2, "c")
    qc = QuantumCircuit(qr, cr, name=f"sync_{stage}_p{scan_phase:.3f}")
    # Alice (qr[0]) shares a Bell pair with Bob (qr[1]).
    qc.h(qr[0])
    qc.cx(qr[0], qr[1])
    # Bob's residual clock offset: idle time and the phase it accumulates.
    if dt_us > 0:
        qc.barrier()
        qc.delay(round(dt_us), qr[1], unit="us")
        qc.barrier()
        qc.rz(omega_rad_per_us * dt_us, qr[1])
    # Probe phase, then both measure in the X basis.
    qc.rz(scan_phase, qr[1])
    qc.h(qr[0])
    qc.h(qr[1])
    qc.measure(qr, cr)
    return qc


CHSH_SETTINGS = (
    ("a_b", 0.0, math.pi / 4, +1),
    ("a_bp", 0.0, -math.pi / 4, +1),
    ("ap_b", math.pi / 2, math.pi / 4, +1),
    ("ap_bp", math.pi / 2, -math.pi / 4, -1),
)


def chsh_circuit(name: str, theta_a: float, theta_b: float) -> QuantumCircuit:
    qr = QuantumRegister(2, "q")
    cr = ClassicalRegister(2, "c")
    qc = QuantumCircuit(qr, cr, name=f"chsh_{name}")
    qc.h(qr[0])
    qc.cx(qr[0], qr[1])
    # ry(-theta) then Z-measurement measures cos(theta) Z + sin(theta) X
    qc.ry(-theta_a, qr[0])
    qc.ry(-theta_b, qr[1])
    qc.measure(qr, cr)
    return qc


# ----------------------------------------------------------------------- metrics
def correlation(counts: dict) -> float:
    """E = P(same) - P(different) over a 2-bit register."""
    total = sum(counts.values())
    same = counts.get("00", 0) + counts.get("11", 0)
    return (2 * same - total) / total


def error_percentage(counts: dict) -> float:
    """Prototype metric: share of anti-correlated outcomes, as a percentage."""
    total = sum(counts.values())
    return 100.0 * (counts.get("01", 0) + counts.get("10", 0)) / total


def pearson_per_shot(bitstrings: list[str]) -> float:
    a = np.array([int(s[-1]) for s in bitstrings], dtype=float)   # classical bit 0
    b = np.array([int(s[-2]) for s in bitstrings], dtype=float)   # classical bit 1
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def fit_fringe(phases, correlations) -> dict:
    """Least squares fit of E(phi) = V*cos(phi + phi0)."""
    phi = np.asarray(phases, dtype=float)
    e = np.asarray(correlations, dtype=float)
    # E = V*cos(phi0)*cos(phi) - V*sin(phi0)*sin(phi): linear in (c, s).
    design = np.stack([np.cos(phi), -np.sin(phi)], axis=1)
    (c, s), *_ = np.linalg.lstsq(design, e, rcond=None)
    visibility = float(math.hypot(c, s))
    phi0 = float(math.atan2(s, c))
    fitted = design @ np.array([c, s])
    ss_res = float(((e - fitted) ** 2).sum())
    ss_tot = float(((e - e.mean()) ** 2).sum())
    return {
        "visibility": visibility,
        "phase_offset_rad": phi0,
        "r_squared": 1.0 - ss_res / ss_tot if ss_tot > 0 else None,
        "residual_rms": math.sqrt(ss_res / len(e)),
    }


def fit_t1(delays_us, populations) -> dict:
    from scipy.optimize import curve_fit

    t = np.asarray(delays_us, dtype=float)
    y = np.asarray(populations, dtype=float)
    if y.max() - y.min() < 0.05:
        return {"t1_us": None, "reason": "no decay observed"}

    def model(x, amp, t1, offset):
        return amp * np.exp(-x / t1) + offset

    try:
        popt, pcov = curve_fit(model, t, y, p0=[y[0] - y[-1], 100.0, y[-1]],
                               bounds=([0.0, 1.0, -0.5], [1.5, 5000.0, 1.0]),
                               maxfev=40000)
        residual = y - model(t, *popt)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        return {
            "t1_us": float(popt[1]),
            "t1_stderr_us": float(math.sqrt(abs(pcov[1][1]))),
            "amplitude": float(popt[0]),
            "offset": float(popt[2]),
            "r_squared": 1.0 - float((residual ** 2).sum()) / ss_tot if ss_tot else None,
        }
    except Exception as exc:  # pragma: no cover
        return {"t1_us": None, "reason": f"fit failed: {exc}"}


# ------------------------------------------------------------------------ stages
def stage_t1(ctx, args) -> float:
    probes = probe_qubits(ctx.backend)
    circuits = t1_circuits(probes)
    isa, isa_metrics = transpile_isa(circuits, ctx.backend, initial_layout=probes)
    estimate = estimate_qpu_seconds(isa, args.t1_shots, ctx.backend)
    print(f"\n=== t1: {len(probes)} probes {probes}")
    print(f"  delays {list(T1_DELAYS_US)} us x {args.t1_shots} shots")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    ideal = run_ideal(circuits, args.t1_shots, method="stabilizer")

    def analyse(records, source_is_ideal: bool):
        populations = {str(q): [] for q in probes}
        for delay_us, rec in zip(T1_DELAYS_US, records):
            total = sum(rec["counts"].values())
            excited = [0] * len(probes)
            for bitstring, n in rec["counts"].items():
                ordered = bitstring.replace(" ", "")[::-1]
                for i in range(len(probes)):
                    if ordered[i] == "1":
                        excited[i] += n
            for i, q in enumerate(probes):
                populations[str(q)].append(excited[i] / total)

        cal = calibration_t1_us(ctx, probes)
        per_qubit, fitted = [], []
        for i, q in enumerate(probes):
            pops = populations[str(q)]
            fit = {"t1_us": None, "reason": "noiseless reference does not decay"} \
                if source_is_ideal else fit_t1(T1_DELAYS_US, pops)
            if fit.get("t1_us"):
                fitted.append(fit["t1_us"])
            per_qubit.append({
                "qubit": q,
                "excited_population": pops,
                "fit": fit,
                "calibration_t1_us": cal[str(q)],
                "fitted_over_reported": (fit["t1_us"] / cal[str(q)]
                                         if fit.get("t1_us") and cal[str(q)] else None),
            })

        reported = [v for v in cal.values() if v]
        summary = {
            "delays_us": list(T1_DELAYS_US),
            "n_probes": len(probes),
            "mean_t1_us": statistics.mean(fitted) if fitted else None,
            "median_t1_us": statistics.median(fitted) if fitted else None,
            "stdev_t1_us": statistics.stdev(fitted) if len(fitted) > 1 else None,
            "min_t1_us": min(fitted) if fitted else None,
            "max_t1_us": max(fitted) if fitted else None,
            "n_fitted": len(fitted),
            "calibration_mean_t1_us": statistics.mean(reported) if reported else None,
            "calibration_median_t1_us": statistics.median(reported) if reported else None,
        }
        return {"summary": summary, "per_qubit": per_qubit}

    ideal_analysis = analyse(ideal, source_is_ideal=True)
    for row in ideal_analysis["per_qubit"]:
        assert all(abs(p - 1.0) < 1e-9 for p in row["excited_population"]), \
            f"noiseless |1> must stay excited, qubit {row['qubit']}"
    print("  ideal: excited population 1.000 at every delay (no relaxation)")

    payload = {
        "run_id": ctx.run_id, "backend": ctx.backend_name, "stage": "t1",
        "probe_qubits": probes, "delays_us": list(T1_DELAYS_US),
        "shots": args.t1_shots, "isa_metrics": isa_metrics,
        "logical_metrics": [circuit_metrics(c) for c in circuits],
        "estimate": estimate,
    }
    ctx.save(EXPERIMENT, "t1_relaxation_ideal",
             {**payload, "source": "AerSimulator (noiseless)",
              "analysis": ideal_analysis, "records": ideal})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, args.t1_shots, tag="qcs_t1")
        analysis = analyse(records, source_is_ideal=False)
        s = analysis["summary"]
        print(f"  hardware: T1 mean {s['mean_t1_us']:.1f} us "
              f"(median {s['median_t1_us']:.1f}, sd {s['stdev_t1_us']:.1f}, "
              f"{s['n_fitted']}/{len(probes)} fitted); "
              f"calibration mean {s['calibration_mean_t1_us']:.1f} us")
        ctx.save(EXPERIMENT, "t1_relaxation",
                 {**payload, "source": f"QPU {ctx.backend_name}",
                  "analysis": analysis, "records": records})
    return estimate["estimated_qpu_seconds"]


def resolve_idle_phase_rate(ctx) -> tuple[float | None, str]:
    """Calibrated parasitic phase per microsecond of idle, if measured."""
    path = ctx.root / EXPERIMENT / "idle_phase_calibration.json"
    if not path.exists():
        return None, "not measured"
    data = json.loads(path.read_text())
    rate = data["analysis"]["idle_phase_rate_rad_per_us"]
    return rate, f"measured on {ctx.backend_name} (idle_phase_calibration.json)"


def stage_phase_cal(ctx, args) -> float:
    """Phase and visibility of a Bell pair versus idle time on Bob's qubit."""
    pair = best_pair(ctx.backend)
    phases = [2 * math.pi * k / PHASE_CAL_PHASES for k in range(PHASE_CAL_PHASES)]
    circuits, index = [], []
    for delay_us in PHASE_CAL_DELAYS_US:
        for i, phase in enumerate(phases):
            qc = sync_circuit("cal", float(delay_us), 0.0, phase)
            qc.name = f"phasecal_{delay_us}us_p{i}"
            circuits.append(qc)
            index.append({"delay_us": delay_us, "scan_phase": phase,
                          "circuit_name": qc.name})

    isa, isa_metrics = transpile_isa(circuits, ctx.backend,
                                     initial_layout=pair["pair"])
    estimate = estimate_qpu_seconds(isa, args.shots, ctx.backend)
    print(f"\n=== phase_cal: {len(PHASE_CAL_DELAYS_US)} delays x "
          f"{PHASE_CAL_PHASES} phases on pair {pair['pair']}")
    print(f"  delays {list(PHASE_CAL_DELAYS_US)} us")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    ideal = run_ideal(circuits, args.shots)

    def analyse(records):
        by_name = {r["circuit_name"]: r for r in records}
        per_delay = []
        for delay_us in PHASE_CAL_DELAYS_US:
            rows = [e for e in index if e["delay_us"] == delay_us]
            corr = [correlation(by_name[e["circuit_name"]]["counts"]) for e in rows]
            fit = fit_fringe([e["scan_phase"] for e in rows], corr)
            per_delay.append({
                "delay_us": delay_us,
                "correlations": corr,
                "visibility": fit["visibility"],
                "phase_offset_rad": fit["phase_offset_rad"],
            })

        delays = np.array([r["delay_us"] for r in per_delay], dtype=float)
        raw_phase = np.array([r["phase_offset_rad"] for r in per_delay])
        unwrapped = np.unwrap(raw_phase)
        slope, intercept = np.polyfit(delays, unwrapped, 1)
        predicted = slope * delays + intercept
        ss_res = float(((unwrapped - predicted) ** 2).sum())
        ss_tot = float(((unwrapped - unwrapped.mean()) ** 2).sum())

        visibility = np.array([r["visibility"] for r in per_delay])
        coherence = {"tau_us": None, "reason": "no decay observed"}
        if visibility.max() > 0 and visibility.min() < visibility.max() * 0.9:
            from scipy.optimize import curve_fit
            try:
                popt, pcov = curve_fit(lambda t, v0, tau: v0 * np.exp(-t / tau),
                                       delays, visibility, p0=[visibility[0], 100.0],
                                       bounds=([0.0, 1.0], [1.5, 1e5]), maxfev=40000)
                coherence = {"v0": float(popt[0]), "tau_us": float(popt[1]),
                             "tau_stderr_us": float(math.sqrt(abs(pcov[1][1])))}
            except Exception as exc:  # pragma: no cover
                coherence = {"tau_us": None, "reason": f"fit failed: {exc}"}

        rate = float(slope)
        return {
            "pair": pair,
            "per_delay": per_delay,
            "unwrapped_phase_rad": unwrapped.tolist(),
            "idle_phase_rate_rad_per_us": rate,
            "idle_phase_intercept_rad": float(intercept),
            "linear_fit_r_squared": 1.0 - ss_res / ss_tot if ss_tot > 0 else None,
            "implied_detuning_khz": rate / (2 * math.pi) * 1e3,
            "phase_wrap_period_us": (2 * math.pi / abs(rate)) if rate else None,
            "entanglement_visibility_decay": coherence,
        }

    ideal_analysis = analyse(ideal)
    max_delay = max(PHASE_CAL_DELAYS_US)
    ideal_phase = abs(ideal_analysis["idle_phase_rate_rad_per_us"]) * max_delay
    # Shot noise alone puts ~0.03 rad of scatter on each fringe phase at 1024
    # shots, so the noiseless bound is on the accumulated phase, not the slope.
    assert ideal_phase < 0.1, \
        f"noiseless idle accumulated {ideal_phase:.3f} rad over {max_delay} us"
    for row in ideal_analysis["per_delay"]:
        assert row["visibility"] > 0.99, \
            f"noiseless visibility fell to {row['visibility']:.3f} at {row['delay_us']} us"
    print(f"  ideal: idle phase {ideal_phase:.4f} rad over {max_delay} us "
          f"(shot noise floor), visibility 1.000 at every delay")

    payload = {
        "run_id": ctx.run_id, "backend": ctx.backend_name, "stage": "phase_cal",
        "delays_us": list(PHASE_CAL_DELAYS_US), "scan_phases": phases,
        "shots": args.shots, "circuit_index": index, "isa_metrics": isa_metrics,
        "logical_metrics": [circuit_metrics(c) for c in circuits],
        "estimate": estimate,
    }
    ctx.save(EXPERIMENT, "idle_phase_calibration_ideal",
             {**payload, "source": "AerSimulator (noiseless)",
              "analysis": ideal_analysis, "records": ideal})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, args.shots, tag="qcs_phase_cal")
        analysis = analyse(records)
        print(f"  hardware: idle phase rate "
              f"{analysis['idle_phase_rate_rad_per_us']:+.4f} rad/us "
              f"({analysis['implied_detuning_khz']:+.2f} kHz, "
              f"R^2 {fmt_opt(analysis['linear_fit_r_squared'])}), "
              f"wraps every {fmt_opt(analysis['phase_wrap_period_us'], '.1f')} us")
        print(f"  hardware: Bell visibility decay tau = "
              f"{fmt_opt(analysis['entanglement_visibility_decay'].get('tau_us'), '.1f')} us")
        ctx.save(EXPERIMENT, "idle_phase_calibration",
                 {**payload, "source": f"QPU {ctx.backend_name}",
                  "analysis": analysis, "records": records})
    return estimate["estimated_qpu_seconds"]


def stage_sync(ctx, args) -> float:
    t1_us, t1_source = resolve_t1_us(ctx, args)
    omega = DRIFT_PHASE_AT_FULL_T1 / t1_us          # rad/us
    idle_rate, idle_source = resolve_idle_phase_rate(ctx)
    phases = [2 * math.pi * k / SCAN_PHASES for k in range(SCAN_PHASES)]
    pair = best_pair(ctx.backend)

    circuits, index = [], []
    for stage, factor in SYNC_STAGES.items():
        dt_us = factor * t1_us
        for phase in phases:
            qc = sync_circuit(stage, dt_us, omega, phase)
            qc.name = f"sync_{stage}_{phases.index(phase)}"
            circuits.append(qc)
            index.append({"stage": stage, "dt_us": dt_us, "scan_phase": phase,
                          "drift_phase_rad": omega * dt_us,
                          "circuit_name": qc.name})

    isa, isa_metrics = transpile_isa(circuits, ctx.backend,
                                     initial_layout=pair["pair"])
    estimate = estimate_qpu_seconds(isa, args.shots, ctx.backend)
    print(f"\n=== sync: three stages x {SCAN_PHASES} scan phases")
    print(f"  T1 = {t1_us:.1f} us ({t1_source}); omega = {omega:.5f} rad/us; "
          f"pair {pair['pair']} (cz error {pair['error']:.5f})")
    print(f"  idle phase rate: {fmt_opt(idle_rate)} rad/us ({idle_source})")
    for stage, factor in SYNC_STAGES.items():
        print(f"    {stage:14s} dt={factor * t1_us:7.1f} us "
              f"drift phase={omega * factor * t1_us:.4f} rad")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    ideal = run_ideal(circuits, args.shots)

    def analyse(records):
        by_name = {r["circuit_name"]: r for r in records}
        stages = {}
        for stage in SYNC_STAGES:
            rows = [e for e in index if e["stage"] == stage]
            corr, pearson, errs = [], [], []
            points = []
            for entry in rows:
                rec = by_name[entry["circuit_name"]]
                counts = rec["counts"]
                e_val = correlation(counts)
                r_val = pearson_per_shot(rec["bitstrings"])
                err = error_percentage(counts)
                corr.append(e_val)
                pearson.append(r_val)
                errs.append(err)
                points.append({
                    "scan_phase": entry["scan_phase"],
                    "correlation": e_val,
                    "pearson_r": r_val,
                    "error_percentage": err,
                    "counts": counts,
                })
            fit = fit_fringe([p["scan_phase"] for p in points], corr)
            dt_applied = rows[0]["dt_us"]
            measured_phase = fit["phase_offset_rad"]
            recovered_dt = measured_phase / omega
            entry_out = {
                "dt_us": dt_applied,
                "applied_drift_phase_rad": rows[0]["drift_phase_rad"],
                "points": points,
                "correlation_at_zero_phase": points[0]["correlation"],
                "pearson_at_zero_phase": points[0]["pearson_r"],
                "error_percentage_at_zero_phase": points[0]["error_percentage"],
                "mean_abs_correlation": mean_std([abs(c) for c in corr])[0],
                "fit": fit,
                "recovered_offset_us": recovered_dt,
                "offset_error_us": recovered_dt - dt_applied,
            }
            if idle_rate is not None:
                # The measured fringe phase is (omega + idle_rate) * dt, known
                # only modulo 2*pi. Blind recovery is therefore unique only
                # within one wrap; the residual below tests the model without
                # using the applied value to fit anything.
                total_rate = omega + idle_rate
                predicted = total_rate * dt_applied
                residual = (measured_phase - predicted + math.pi) % (2 * math.pi) - math.pi
                wraps = round((predicted - measured_phase) / (2 * math.pi))
                entry_out["calibrated"] = {
                    "idle_phase_rate_rad_per_us": idle_rate,
                    "total_phase_rate_rad_per_us": total_rate,
                    "predicted_phase_rad": predicted,
                    "model_residual_rad": residual,
                    "phase_wraps": wraps,
                    "recovered_offset_us": (measured_phase + 2 * math.pi * wraps) / total_rate,
                    "offset_error_us": ((measured_phase + 2 * math.pi * wraps) / total_rate
                                        - dt_applied),
                    "unambiguous_range_us": 2 * math.pi / abs(total_rate),
                }
            stages[stage] = entry_out
        return {
            "t1_us": t1_us,
            "t1_source": t1_source,
            "omega_rad_per_us": omega,
            "idle_phase_rate_rad_per_us": idle_rate,
            "idle_phase_source": idle_source,
            "scan_phases": phases,
            "pair": pair,
            "stages": stages,
            "visibility_by_stage": {k: v["fit"]["visibility"] for k, v in stages.items()},
        }

    ideal_analysis = analyse(ideal)
    assert abs(ideal_analysis["stages"]["synced"]["correlation_at_zero_phase"] - 1.0) < 0.05, \
        "noiseless synced stage must be perfectly correlated"
    for stage, data in ideal_analysis["stages"].items():
        assert data["fit"]["visibility"] > 0.9, \
            f"noiseless fringe visibility collapsed for {stage}"
    print("  ideal: visibility " + ", ".join(
        f"{k}={v:.3f}" for k, v in ideal_analysis["visibility_by_stage"].items()))
    print("  ideal: E(phi=0) " + ", ".join(
        f"{k}={v['correlation_at_zero_phase']:+.3f}"
        for k, v in ideal_analysis["stages"].items()))

    payload = {
        "run_id": ctx.run_id, "backend": ctx.backend_name, "stage": "sync",
        "stage_factors": SYNC_STAGES, "shots": args.shots,
        "circuit_index": index, "isa_metrics": isa_metrics,
        "logical_metrics": [circuit_metrics(c) for c in circuits],
        "estimate": estimate,
    }
    ctx.save(EXPERIMENT, "sync_three_stage_ideal",
             {**payload, "source": "AerSimulator (noiseless)",
              "analysis": ideal_analysis, "records": ideal})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, args.shots, tag="qcs_sync")
        analysis = analyse(records)
        for stage, data in analysis["stages"].items():
            print(f"  hardware {stage:14s} E(0)={data['correlation_at_zero_phase']:+.3f} "
                  f"V={data['fit']['visibility']:.3f} "
                  f"err={data['error_percentage_at_zero_phase']:.2f}% "
                  f"phase={data['fit']['phase_offset_rad']:+.3f} rad "
                  f"(applied {data['dt_us']:.1f} us)")
            cal = data.get("calibrated")
            if cal:
                print(f"    calibrated: predicted {cal['predicted_phase_rad']:+.3f} rad, "
                      f"residual {cal['model_residual_rad']:+.3f} rad, "
                      f"{cal['phase_wraps']} wraps, recovered "
                      f"{cal['recovered_offset_us']:+.1f} us "
                      f"(error {cal['offset_error_us']:+.1f}, unambiguous below "
                      f"{cal['unambiguous_range_us']:.1f} us)")
        ctx.save(EXPERIMENT, "sync_three_stage",
                 {**payload, "source": f"QPU {ctx.backend_name}",
                  "analysis": analysis, "records": records})
    return estimate["estimated_qpu_seconds"]


def stage_chsh(ctx, args) -> float:
    pair = best_pair(ctx.backend)
    circuits = [chsh_circuit(name, ta, tb) for name, ta, tb, _ in CHSH_SETTINGS]
    isa, isa_metrics = transpile_isa(circuits, ctx.backend,
                                     initial_layout=pair["pair"])
    estimate = estimate_qpu_seconds(isa, args.shots, ctx.backend)
    print(f"\n=== chsh: 4 settings on pair {pair['pair']}")
    print(f"  estimate {estimate['estimated_qpu_seconds']:.1f} QPU-s")

    ideal = run_ideal(circuits, args.shots)

    def analyse(records):
        terms = {}
        s_value = 0.0
        for (name, ta, tb, sign), rec in zip(CHSH_SETTINGS, records):
            e_val = correlation(rec["counts"])
            terms[name] = {"theta_a": ta, "theta_b": tb, "sign": sign,
                           "correlation": e_val, "counts": rec["counts"]}
            s_value += sign * e_val
        return {
            "pair": pair,
            "terms": terms,
            "S": s_value,
            "classical_bound": 2.0,
            "tsirelson_bound": 2 * math.sqrt(2),
            "violates_classical_bound": abs(s_value) > 2.0,
        }

    ideal_analysis = analyse(ideal)
    print(f"  ideal: S = {ideal_analysis['S']:.4f} "
          f"(Tsirelson {ideal_analysis['tsirelson_bound']:.4f})")
    assert abs(abs(ideal_analysis["S"]) - 2 * math.sqrt(2)) < 0.1, \
        "noiseless CHSH must reach the Tsirelson bound"

    payload = {
        "run_id": ctx.run_id, "backend": ctx.backend_name, "stage": "chsh",
        "shots": args.shots, "settings": [list(s) for s in CHSH_SETTINGS],
        "isa_metrics": isa_metrics,
        "logical_metrics": [circuit_metrics(c) for c in circuits],
        "estimate": estimate,
    }
    ctx.save(EXPERIMENT, "chsh_ideal",
             {**payload, "source": "AerSimulator (noiseless)",
              "analysis": ideal_analysis, "records": ideal})

    if args.submit:
        assert_budget(estimate, reserve_seconds=args.reserve)
        records = run_sampler(ctx, isa, args.shots, tag="qcs_chsh")
        analysis = analyse(records)
        print(f"  hardware: S = {analysis['S']:.4f} "
              f"({'violates' if analysis['violates_classical_bound'] else 'does NOT violate'}"
              f" the classical bound of 2)")
        ctx.save(EXPERIMENT, "chsh",
                 {**payload, "source": f"QPU {ctx.backend_name}",
                  "analysis": analysis, "records": records})
    return estimate["estimated_qpu_seconds"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--t1-shots", type=int, default=T1_SHOTS)
    parser.add_argument("--t1-us", type=float, default=None,
                        help="override the T1 used to scale the sync stages")
    parser.add_argument("--stage", default="all",
                        choices=["t1", "phase_cal", "sync", "chsh", "all"])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--reserve", type=float, default=60.0)
    args = parser.parse_args(argv)

    ctx = open_run(run_id=args.run_id)
    total = 0.0
    if args.stage in ("t1", "all"):
        total += stage_t1(ctx, args)
    if args.stage in ("phase_cal", "all"):
        total += stage_phase_cal(ctx, args)
    if args.stage in ("sync", "all"):
        total += stage_sync(ctx, args)
    if args.stage in ("chsh", "all"):
        total += stage_chsh(ctx, args)

    print(f"\nTOTAL estimated QPU seconds: {total:.1f}")
    if not args.submit:
        print("dry run only - add --submit to spend QPU time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
