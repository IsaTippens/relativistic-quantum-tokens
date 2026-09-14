"""Survey operational QPUs on the us-east 'qpus' instance and pick one.

    venv/bin/python experiments/ibm/select_backend.py

Prints the ranking table and writes results/backend_survey.json.
The chosen backend is the one open_run() would bind.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ibm.common import RESULTS_ROOT, backend_health, get_service, select_backend


def main() -> None:
    service = get_service()
    print(f"instance CRN: {getattr(service, '_omp_crn', '?')}")
    chosen, survey = select_backend()

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    out = RESULTS_ROOT / "backend_survey.json"
    out.write_text(json.dumps({
        "surveyed_at_utc": datetime.now(timezone.utc).isoformat(),
        "chosen": chosen.name,
        "backends": survey,
    }, indent=2, default=str))

    hdr = (f"{'backend':16s} {'nq':>4s} {'cal_age_h':>9s} {'2q_err':>8s} "
           f"{'ro_err':>7s} {'T1_us':>7s} {'T2_us':>7s} {'queue':>5s}")
    print(hdr)
    print("-" * len(hdr))
    for r in survey:
        mark = " <== chosen" if r["name"] == chosen.name else ""
        print(f"{r['name']:16s} {r['num_qubits']:4d} "
              f"{(r['calibration_age_hours'] if r['calibration_age_hours'] is not None else -1):9.2f} "
              f"{(r['median_2q_error'] or 0):8.5f} {(r['median_readout_error'] or 0):7.4f} "
              f"{(r['median_t1_us'] or 0):7.1f} {(r['median_t2_us'] or 0):7.1f} "
              f"{r['pending_jobs']:5d}{mark}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
