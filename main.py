import logging
import argparse
from entities.bank import Bank
from entities.alice_wallet import AliceWallet
from entities.merchant import Merchant
from utils.ibm_connector import get_ibm_sampler

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    parser = argparse.ArgumentParser(description="Run Quantum-Secured Token Protocol.")
    parser.add_argument("--cloud", action="store_true", help="Use IBM Quantum Cloud for the hashing circuit.")
    args = parser.parse_args()

    logger.info("=== Starting Quantum-Secured Token Protocol MVP ===")
    
    # 1. Initialization
    sampler = get_ibm_sampler(use_cloud=args.cloud)
    
    bank = Bank(sampler=sampler)
    alice = AliceWallet(sampler=sampler)
    charlie = Merchant(name="Starbucks_Geohash_x7y8z", location_geohash="gbsuv7uuuuuu")

    # 2. Key Generation (BB84)
    logger.info("--- Phase 1: Key Generation ---")
    shared_secret = bank.perform_bb84_exchange(alice)
    
    # 3. Issuance
    logger.info("--- Phase 2: Token Issuance ---")
    serial_number = bank.issue_serial_number(shared_secret)
    alice.receive_serial_number(bank.send_serial_number(serial_number))
    
    # 4. The Spend
    logger.info("--- Phase 3: The Spend ---")
    try:
        token_transmission = alice.spend_at_merchant(charlie)
        
        # 5. Settlement and Verification
        logger.info("--- Phase 4: Settlement ---")
        success = charlie.receive_token_and_settle(token_transmission, bank)
        
        if success:
            logger.info("=== Protocol Execution Successful ===")
        else:
            logger.error("=== Protocol Execution Failed Verification ===")
            
    except Exception as e:
        logger.error(f"Error during protocol execution: {e}")

if __name__ == "__main__":
    main()
