#!/usr/bin/env python3
"""
Script to run ML integration.
"""

import os
import sys
import logging
import subprocess
import argparse
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/ml_integration.log')
    ]
)
logger = logging.getLogger(__name__)

def setup_ml_environment():
    """Set up ML environment."""
    try:
        # Create required directories
        logger.info("Setting up ML environment")
        subprocess.check_call([sys.executable, "ml/setup_ml.py"])
        
        # Initialize models
        logger.info("Initializing ML models")
        subprocess.check_call([sys.executable, "ml/utils/model_init.py"])
        
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error setting up ML environment: {e}")
        return False

def run_paper_trading(days=1.0, use_ml=True):
    """Run paper trading with ML integration.
    
    Args:
        days: Duration in days to run paper trading
        use_ml: Whether to use ML model
    """
    try:
        cmd = [sys.executable, "run_paper_trading.py", f"--days={days}"]
        if not use_ml:
            cmd.append("--no-ml")
            
        logger.info(f"Running paper trading command: {' '.join(cmd)}")
        subprocess.check_call(cmd)
        
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running paper trading: {e}")
        return False

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Run ML integration')
    parser.add_argument('--days', type=float, default=1.0, 
                      help='Duration in days to run paper trading')
    parser.add_argument('--no-ml', action='store_true', default=False,
                      help='Disable ML model and use baseline strategy')
    args = parser.parse_args()
    
    # Set up ML environment
    if not setup_ml_environment():
        logger.error("Failed to set up ML environment")
        return 1
        
    # Run paper trading
    if not run_paper_trading(days=args.days, use_ml=not args.no_ml):
        logger.error("Paper trading failed")
        return 1
        
    logger.info("ML integration completed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main()) 