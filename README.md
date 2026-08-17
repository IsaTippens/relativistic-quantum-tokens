# A Framework for Secure Financial Transactions with Relativistic Quantum Tokens

Prototype framework accompanying the thesis *"A Framework for Secure Financial Transactions with Relativistic Quantum Tokens"*. It simulates a quantum-secured token protocol (S-money / relativistic hybrid) in which a bank issues unclonable tokens to a client (Alice), who spends them at a merchant/proxy (Charlie) under time and location constraints.

## Protocol Overview

1. **Key Generation (BB84):** Alice and the Bank perform a simulated BB84 quantum key exchange, producing a shared classical secret.
2. **Issuance:** The Bank generates a serial number and stores `[Serial Number : Secret State]` with `ACTIVE` status in an SQLite ledger.
3. **Token Programming:** Alice binds the token to a target geohash and expiration timestamp, signing the constraints with a Grover-based quantum hash (Amplitude-Amplification Hash). The payload is transmitted via superdense coding.
4. **Settlement:** Charlie appends his observed time and geohash and proxies the bundle to the Bank. The Bank verifies temporal/geographic validity and re-runs the quantum hash; on match, the ledger entry is marked `SPENT`.

Verified adversarial cases: geographic spoofing, temporal expiration, payload tampering, and double spending.

## Repository Layout

| Path | Contents |
|---|---|
| `entities/` | Protocol participants: `Bank`, `BankNode`, `AliceWallet`, `AliceNode`, `Merchant`, `CharlieNode`, `CentralSource`, `TimeNode` |
| `quantum_circuits/` | Quantum primitives: BB84, superdense coding, Grover hash (linear + Feistel oracle), quantum-walk hashes, time-sync simulator |
| `webapp/` | Flask demo visualizing the bank ledger, Alice, and Charlie views |
| `scripts/` | Runnable generators: E2E metrics, test artifacts, latency spike, IBM credential setup |
| `tests/` | pytest suite: E2E token flow, components, superdense coding, time-sync correlation |
| `benchmarks/` | Hash-function benchmarks (Hamming distance, uniformity) and comparison report |
| `thesis_figures/` | Circuit diagrams and explanatory text used in the thesis |
| `docs/` | Design notes and E2E system validation write-up |

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r tests/requirements_test.txt
```

Optional (IBM Quantum hardware execution):

```bash
python scripts/setup_ibm.py --token YOUR_IBM_QUANTUM_TOKEN
```

## Usage

Run the MVP protocol (local Aer simulation; add `--cloud` for IBM hardware):

```bash
python main.py
```

Run the time-synchronization demo:

```bash
python time_sync_main.py
```

Launch the web demo:

```bash
python webapp/app.py   # http://127.0.0.1:5000
```

All scripts under `scripts/` can be run from any directory; they resolve the repository root automatically:

```bash
python scripts/generate_e2e_results.py   # latency metrics -> output/
python scripts/generate_artifacts.py     # test run + figures -> test_artifacts/
python scripts/latency_spike.py          # per-phase latency printout
```

## Tests

```bash
python -m pytest tests/ -v
```

The time-sync correlation graph (saved to `benchmarks/correlation_graph.png`):

```bash
python tests/test_correlation_graph.py            # add --cloud for hardware overlay
```
