import argparse
from qiskit_ibm_runtime import QiskitRuntimeService

def main():
    parser = argparse.ArgumentParser(description="Save IBM Quantum credentials.")
    parser.add_argument("--token", type=str, default="YOUR_IBM_QUANTUM_TOKEN_HERE", help="IBM Quantum API token")
    args = parser.parse_args()

    print("Saving IBM Quantum Account...")
    try:
        QiskitRuntimeService.save_account(token=args.token, channel="ibm_quantum", overwrite=True)
        print("Account saved successfully!")
    except Exception as e:
        print(f"Error saving account: {e}")

if __name__ == "__main__":
    main()
