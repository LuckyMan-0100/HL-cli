#!/usr/bin/env python3
"""
Wrapper script to run paper trading with correct Python path.
"""
import os
import sys

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Now we can import from scripts
from scripts.run_paper_trading import main

if __name__ == "__main__":
    main() 