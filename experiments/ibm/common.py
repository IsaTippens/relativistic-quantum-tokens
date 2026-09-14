"""Shared infrastructure for the IBM Quantum hardware runs.

Every experiment in experiments/ibm/ uses this module so that all artifacts
land in one run directory with a consistent shape:

    results/<RUN_ID>/
        run_manifest.json          # backend, instance, calibration snapshot ref
        calibration_<backend>.json # full per-qubit / per-pair calibration dump
        jobs.json                  # append-only log of every submitted job id
        <experiment>/...json       # per-experiment payloads (counts + metadata)

The IBM account is the "qpus" instance (plan: open, region: us-east) reached
with the IBM_CLOUD_API_KEY in .env.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = PROJECT_ROOT / "results"
ENV_PATH = PROJECT_ROOT / ".env"

INSTANCE_NAME = "qpus"
INSTANCE_REGION = "us-east"
CHANNEL = "ibm_quantum_platform"

# Chunk size for PUBs per job: keeps payloads well inside service limits while
# still amortising the per-job overhead across many circuits.
MAX_PUBS_PER_JOB = 60


# --------------------------------------------------------------------------- env
def load_token() -> str:
    tok = os.environ.get("IBM_CLOUD_API_KEY")
    if tok:
        return tok.strip()
    if not ENV_PATH.exists():
        raise RuntimeError(f"no IBM_CLOUD_API_KEY in env and no {ENV_PATH}")
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        if key.strip() == "IBM_CLOUD_API_KEY":
            return val.strip().strip('"').strip("'")
    raise RuntimeError(f"IBM_CLOUD_API_KEY not found in {ENV_PATH}")


_SERVICE = None


def get_service():
    """QiskitRuntimeService bound to the us-east 'qpus' open-plan instance."""
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    from qiskit_ibm_runtime import QiskitRuntimeService

    token = load_token()
    probe = QiskitRuntimeService(channel=CHANNEL, token=token)
    crn = None
    for inst in probe.instances():
        if inst.get("name") == INSTANCE_NAME and INSTANCE_REGION in inst.get("crn", ""):
            crn = inst["crn"]
            break
    if crn is None:
        raise RuntimeError(
            f"instance {INSTANCE_NAME!r} in {INSTANCE_REGION} not visible to this API key; "
            f"saw {[i.get('name') for i in probe.instances()]}"
        )
    _SERVICE = QiskitRuntimeService(channel=CHANNEL, token=token, instance=crn)
    _SERVICE._omp_crn = crn  # noqa: SLF001  (recorded in the manifest)
    return _SERVICE


# ------------------------------------------------------------------ backend pick
def backend_health(backend) -> dict:
    """Calibration freshness + median error rates for one backend."""
    props = backend.properties()
    status = backend.status()
    target = backend.target

    t1s, t2s, ro = [], [], []
    if props is not None:
        for q in range(backend.num_qubits):
            try:
                t1s.append(props.t1(q))
                t2s.append(props.t2(q))
                ro.append(props.readout_error(q))
            except Exception:
                pass

    two_q_errs, two_q_name = [], None
    for name in ("cz", "ecr", "cx"):
        if name in target.operation_names:
            two_q_name = name
            for qargs, inst in target[name].items():
                if inst is not None and inst.error is not None and qargs and len(qargs) == 2:
                    two_q_errs.append(inst.error)
            break

    last_cal = getattr(props, "last_update_date", None)
    age_h = None
    if last_cal is not None:
        last_cal = last_cal.astimezone(timezone.utc)
        age_h = (datetime.now(timezone.utc) - last_cal).total_seconds() / 3600.0

    return {
        "name": backend.name,
        "num_qubits": backend.num_qubits,
        "processor_type": getattr(backend, "processor_type", None),
        "two_qubit_gate": two_q_name,
        "pending_jobs": status.pending_jobs,
        "operational": status.operational,
        "last_calibration_utc": last_cal.isoformat() if last_cal else None,
        "calibration_age_hours": round(age_h, 3) if age_h is not None else None,
        "median_t1_us": round(statistics.median(t1s) * 1e6, 2) if t1s else None,
        "median_t2_us": round(statistics.median(t2s) * 1e6, 2) if t2s else None,
        "median_readout_error": round(statistics.median(ro), 6) if ro else None,
        "median_2q_error": round(statistics.median(two_q_errs), 6) if two_q_errs else None,
        "dt_seconds": getattr(backend, "dt", None),
    }


def select_backend(min_qubits: int = 27, max_calibration_age_hours: float = 24.0,
                   max_pending_jobs: int = 20):
    """Pick one recently calibrated, actually-usable QPU.

    Filters: operational, >= min_qubits, calibration fresher than
    max_calibration_age_hours, and a queue no deeper than max_pending_jobs (a
    186-job queue on the open plan costs hours of wall time and the calibration
    would be stale by the time the last job lands, which defeats the point of
    pinning one freshly calibrated device for the whole run).
    Ranking key = (median 2-qubit gate error, calibration age).
    """
    service = get_service()
    healths = []
    for backend in service.backends(simulator=False, operational=True):
        if backend.num_qubits < min_qubits:
            continue
        try:
            healths.append((backend, backend_health(backend)))
        except Exception as exc:  # pragma: no cover - transient service errors
            print(f"  skip {backend.name}: {exc}")
    if not healths:
        raise RuntimeError("no operational QPUs visible")

    def eligible(h):
        return ((h[1]["calibration_age_hours"] or 1e9) <= max_calibration_age_hours
                and h[1]["pending_jobs"] <= max_pending_jobs)

    pool = [h for h in healths if eligible(h)] or healths
    pool.sort(key=lambda h: (h[1]["median_2q_error"] or 1.0, h[1]["calibration_age_hours"] or 1e9))
    return pool[0][0], [h[1] for h in sorted(healths, key=lambda h: (h[1]["median_2q_error"] or 1.0))]


def calibration_snapshot(backend) -> dict:
    """Full calibration dump: per-qubit coherence/readout + per-pair 2q errors."""
    props = backend.properties()
    target = backend.target
    qubits = {}
    for q in range(backend.num_qubits):
        entry = {}
        for field_name, getter in (
            ("t1_s", props.t1), ("t2_s", props.t2), ("frequency_hz", props.frequency),
            ("readout_error", props.readout_error),
        ):
            try:
                entry[field_name] = getter(q)
            except Exception:
                entry[field_name] = None
        for gate in ("sx", "x", "rz"):
            try:
                entry[f"{gate}_error"] = props.gate_error(gate, q)
                entry[f"{gate}_length_s"] = props.gate_length(gate, q)
            except Exception:
                pass
        qubits[str(q)] = entry

    pairs = {}
    for name in ("cz", "ecr", "cx"):
        if name in target.operation_names:
            for qargs, inst in target[name].items():
                if not qargs or len(qargs) != 2 or inst is None:
                    continue
                pairs[f"{qargs[0]}_{qargs[1]}"] = {
                    "gate": name,
                    "error": inst.error,
                    "duration_s": inst.duration,
                }
            break

    last_cal = getattr(props, "last_update_date", None)
    return {
        "backend": backend.name,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_calibration_utc": last_cal.astimezone(timezone.utc).isoformat() if last_cal else None,
        "num_qubits": backend.num_qubits,
        "basis_gates": sorted(target.operation_names),
        "dt_seconds": getattr(backend, "dt", None),
        "max_delay_dt": getattr(getattr(backend, "configuration", lambda: None)(), "max_delay", None)
        if hasattr(backend, "configuration") else None,
        "qubits": qubits,
        "two_qubit_pairs": pairs,
        "health": backend_health(backend),
    }


# ------------------------------------------------------------------- run context
@dataclass
class RunContext:
    run_id: str
    backend_name: str
    root: Path
    backend: object = None
    _jobs: list = field(default_factory=list)

    @property
    def jobs_path(self) -> Path:
        return self.root / "jobs.json"

    def log_job(self, entry: dict) -> None:
        self._jobs.append(entry)
        existing = []
        if self.jobs_path.exists():
            existing = json.loads(self.jobs_path.read_text())
        existing.append(entry)
        self.jobs_path.write_text(json.dumps(existing, indent=2))

    def save(self, experiment: str, name: str, payload: dict) -> Path:
        out_dir = self.root / experiment
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, default=_json_default))
        print(f"  saved {path.relative_to(PROJECT_ROOT)}")
        return path


def _json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, complex):
        return [obj.real, obj.imag]
    return str(obj)


def open_run(run_id: str | None = None, backend_name: str | None = None,
             fresh_backend: bool = False) -> RunContext:
    """Attach to (or create) a run directory and bind the chosen backend.

    The run manifest is written once; later experiments reuse the same backend
    so that every artifact in a run comes from a single QPU.
    """
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    if run_id is None:
        run_id = os.environ.get("OMP_RUN_ID") or _latest_run_id()
    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("ibmq_%Y%m%dT%H%M%SZ")

    root = RESULTS_ROOT / run_id
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "run_manifest.json"

    service = get_service()
    if manifest_path.exists() and not fresh_backend:
        manifest = json.loads(manifest_path.read_text())
        backend_name = backend_name or manifest["backend"]["name"]
        backend = service.backend(backend_name)
    else:
        if backend_name:
            # Still survey every candidate: the manifest has to justify the
            # choice even when the backend was named explicitly.
            backend = service.backend(backend_name)
            _, survey = select_backend()
        else:
            backend, survey = select_backend()
        manifest = {
            "run_id": run_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "channel": CHANNEL,
            "instance_name": INSTANCE_NAME,
            "instance_region": INSTANCE_REGION,
            "instance_crn": getattr(service, "_omp_crn", None),
            "backend": backend_health(backend),
            "backend_survey": survey,
            "selection_rule": "operational, >=27 qubits, calibration age <= 24 h, "
                              "queue depth <= 20 pending jobs, ranked by median "
                              "2-qubit gate error then calibration freshness",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, default=_json_default))
        cal = calibration_snapshot(backend)
        (root / f"calibration_{backend.name}.json").write_text(
            json.dumps(cal, indent=2, default=_json_default))
        print(f"  manifest + calibration written for {backend.name}")

    ctx = RunContext(run_id=run_id, backend_name=backend.name, root=root, backend=backend)
    print(f"[run {run_id}] backend={backend.name}")
    return ctx


def _latest_run_id() -> str | None:
    if not RESULTS_ROOT.exists():
        return None
    runs = sorted(p.name for p in RESULTS_ROOT.iterdir()
                  if p.is_dir() and p.name.startswith("ibmq_"))
    return runs[-1] if runs else None


# ------------------------------------------------------------------- transpiling
def transpile_isa(circuits, backend, optimization_level: int = 3, seed: int = 1337,
                  initial_layout=None):
    """Transpile to the backend ISA. Returns (isa_circuits, metrics).

    ``initial_layout`` pins the physical qubits. Required whenever the metric
    is tied to specific hardware qubits (T1 probes, a named coupled pair):
    circuits with no two-qubit gates give the layout pass nothing to optimise,
    so it is free to place them anywhere and the per-qubit comparison against
    the calibration data would be meaningless.
    """
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    single = not isinstance(circuits, (list, tuple))
    circs = [circuits] if single else list(circuits)
    pm = generate_preset_pass_manager(optimization_level=optimization_level,
                                      backend=backend, seed_transpiler=seed,
                                      initial_layout=initial_layout)
    isa = pm.run(circs)
    metrics = [circuit_metrics(c) for c in isa]
    return (isa[0] if single else isa), metrics


def circuit_metrics(circuit) -> dict:
    ops = circuit.count_ops()
    two_q = sum(v for k, v in ops.items() if k in ("cz", "ecr", "cx", "cy", "ch", "swap"))
    return {
        "name": circuit.name,
        "num_qubits": circuit.num_qubits,
        "depth": circuit.depth(),
        "two_qubit_gates": two_q,
        "ops": {k: int(v) for k, v in ops.items()},
    }


# --------------------------------------------------------------------- budgeting
# ibm_fez: dynamic_reprate_enabled, default_rep_delay = 250 us, range [0, 2 ms].
# QPU time is dominated by shots x (circuit duration + rep_delay), so the idle
# reset window is the floor on cost for shallow circuits. Left at the device
# default: shortening it trades state-preparation fidelity for billing.
REP_DELAY_S = 250e-6
JOB_OVERHEAD_S = 2.0


def estimate_qpu_seconds(isa_circuits, shots: int, backend,
                         rep_delay_s: float = REP_DELAY_S,
                         job_overhead_s: float = JOB_OVERHEAD_S) -> dict:
    """Predict billed QPU seconds for a submission before spending any.

    The open plan grants 600 s per 28 days, so every runner prints this and
    checks it against usage_remaining_seconds before submitting.
    """
    circs = list(isa_circuits)
    durations = []
    for c in circs:
        try:
            durations.append(float(c.estimate_duration(backend.target, unit="s")))
        except Exception:
            durations.append(0.0)
    per_circuit = [shots * (d + rep_delay_s) for d in durations]
    n_jobs = max(1, math.ceil(len(circs) / MAX_PUBS_PER_JOB)) if circs else 0
    return {
        "n_circuits": len(circs),
        "shots": shots,
        "n_jobs": n_jobs,
        "rep_delay_s": rep_delay_s,
        "mean_circuit_duration_s": (sum(durations) / len(durations)) if durations else 0.0,
        "max_circuit_duration_s": max(durations) if durations else 0.0,
        "estimated_qpu_seconds": round(sum(per_circuit) + n_jobs * job_overhead_s, 2),
    }


def usage_remaining_seconds() -> float | None:
    try:
        usage = get_service().usage()
    except Exception:
        return None
    return usage.get("usage_remaining_seconds")


def assert_budget(estimate: dict, reserve_seconds: float = 60.0) -> float | None:
    """Refuse to submit if the estimate would eat into the reserve."""
    remaining = usage_remaining_seconds()
    est = estimate["estimated_qpu_seconds"]
    print(f"  budget: estimate {est:.1f}s vs remaining "
          f"{remaining if remaining is not None else '?'}s (reserve {reserve_seconds}s)")
    if remaining is not None and est > max(0.0, remaining - reserve_seconds):
        raise RuntimeError(
            f"submission would exceed the open-plan budget: need {est:.1f}s, "
            f"remaining {remaining}s, reserve {reserve_seconds}s")
    return remaining

# ------------------------------------------------------------------- submission
def run_sampler(ctx: RunContext, isa_circuits: Sequence, shots: int, tag: str,
                metadata: dict | None = None) -> list[dict]:
    """Submit ISA circuits to the QPU in chunks, return one record per circuit.

    Each record: {counts, shots, bitstrings (optional), job_id, index}.
    Job ids are logged to jobs.json *before* waiting, so a dropped connection
    never loses the run.
    """
    from qiskit_ibm_runtime import SamplerV2

    sampler = SamplerV2(mode=ctx.backend)
    sampler.options.default_shots = shots

    records: list[dict] = []
    chunks = [list(isa_circuits[i:i + MAX_PUBS_PER_JOB])
              for i in range(0, len(isa_circuits), MAX_PUBS_PER_JOB)]
    for ci, chunk in enumerate(chunks):
        t0 = time.time()
        job = sampler.run(chunk, shots=shots)
        entry = {
            "tag": tag,
            "chunk": ci,
            "job_id": job.job_id(),
            "backend": ctx.backend_name,
            "n_circuits": len(chunk),
            "shots": shots,
            "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        ctx.log_job(entry)
        print(f"  [{tag}] job {job.job_id()} chunk {ci + 1}/{len(chunks)} "
              f"({len(chunk)} circuits x {shots} shots) submitted")
        result = job.result()
        wall = time.time() - t0
        usage = None
        try:
            usage = job.usage_estimation
        except Exception:
            pass
        try:
            metrics = job.metrics()
            usage_s = metrics.get("usage", {}).get("quantum_seconds")
        except Exception:
            usage_s = None
        print(f"  [{tag}] job {job.job_id()} done in {wall:.1f}s "
              f"(quantum_seconds={usage_s})")

        for i, pub in enumerate(result):
            counts, per_shot, creg = extract_counts(pub)
            records.append({
                "index": ci * MAX_PUBS_PER_JOB + i,
                "circuit_name": chunk[i].name,
                "job_id": job.job_id(),
                "creg": creg,
                "shots": shots,
                "counts": counts,
                "bitstrings": per_shot,
            })
        entry["wall_seconds"] = round(wall, 2)
        entry["quantum_seconds"] = usage_s
        entry["usage_estimation"] = usage
        _rewrite_job_entry(ctx, entry)
    return records


def _rewrite_job_entry(ctx: RunContext, entry: dict) -> None:
    if not ctx.jobs_path.exists():
        return
    data = json.loads(ctx.jobs_path.read_text())
    for i, e in enumerate(data):
        if e.get("job_id") == entry["job_id"] and e.get("chunk") == entry.get("chunk"):
            data[i] = entry
    ctx.jobs_path.write_text(json.dumps(data, indent=2, default=_json_default))


def extract_counts(pub_result, keep_shots: bool = True):
    """Pull counts (and per-shot bitstrings) out of a SamplerV2 PUB result."""
    data = pub_result.data
    fields = list(data.keys()) if hasattr(data, "keys") else []
    if not fields:
        raise RuntimeError("PUB result carries no classical registers")
    creg = fields[0]
    bit_array = getattr(data, creg)
    counts = {k: int(v) for k, v in bit_array.get_counts().items()}
    per_shot = bit_array.get_bitstrings() if keep_shots else None
    return counts, per_shot, creg


def run_ideal(circuits, shots: int, seed: int = 42, method: str = "automatic") -> list[dict]:
    """Noiseless AerSimulator reference for the same logical circuits."""
    from qiskit import transpile
    from qiskit_aer import AerSimulator

    sim = AerSimulator(method=method)
    circs = list(circuits)
    tqc = transpile(circs, sim)
    job = sim.run(tqc, shots=shots, seed_simulator=seed, memory=True)
    res = job.result()
    out = []
    for i, c in enumerate(circs):
        out.append({
            "index": i,
            "circuit_name": c.name,
            "counts": {k.replace(" ", ""): int(v) for k, v in res.get_counts(i).items()},
            "bitstrings": [m.replace(" ", "") for m in res.get_memory(i)],
            "shots": shots,
        })
    return out


# ----------------------------------------------------------------------- helpers
def hamming(a: str, b: str) -> int:
    if len(a) != len(b):
        raise ValueError(f"length mismatch {len(a)} vs {len(b)}")
    return sum(x != y for x, y in zip(a, b))


def top_bitstring(counts: dict) -> str:
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def shannon_entropy(counts: dict) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    acc = 0.0
    for v in counts.values():
        if v:
            p = v / total
            acc -= p * math.log2(p)
    return acc


def total_variation(counts_a: dict, counts_b: dict) -> float:
    """TVD between two count dicts (normalised)."""
    ta, tb = sum(counts_a.values()), sum(counts_b.values())
    keys = set(counts_a) | set(counts_b)
    return 0.5 * sum(abs(counts_a.get(k, 0) / ta - counts_b.get(k, 0) / tb) for k in keys)


def hellinger_fidelity(counts_a: dict, counts_b: dict) -> float:
    ta, tb = sum(counts_a.values()), sum(counts_b.values())
    keys = set(counts_a) | set(counts_b)
    bc = sum(math.sqrt((counts_a.get(k, 0) / ta) * (counts_b.get(k, 0) / tb)) for k in keys)
    return bc ** 2


def mean_std(xs: Iterable[float]) -> tuple[float, float]:
    xs = list(xs)
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return m, 0.0
    return m, statistics.stdev(xs)
