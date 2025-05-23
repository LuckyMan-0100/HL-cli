import os
import sys
from dotenv import load_dotenv

# Add the cpp_exec/build directory to sys.path to find the .so file
# Adjust the path if your .so file is in a different subdirectory of build
# e.g., if it's in build/lib or build/Debug etc.
# Assuming the .so is named exec_bridge.cpython-39-darwin.so or similar
# and is directly in the build directory.

# Get the project root directory (HL-cli)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Path to the build directory
build_dir = os.path.join(project_root, 'cpp_exec', 'build')
sys.path.insert(0, build_dir)

try:
    import exec_bridge 
except ImportError as e:
    print(f"Error importing exec_bridge: {e}")
    print(f"Please ensure 'exec_bridge.so' (or similar name like exec_bridge.cpython-XX-darwin.so) exists in {build_dir} or a library output directory within it.")
    sys.exit(1)

def main():
    load_dotenv() # Load environment variables from .env file

    api_key = os.getenv("BACKPACK_API_KEY")
    api_secret = os.getenv("BACKPACK_API_SECRET_B64")

    if not api_key or not api_secret:
        print("Error: BACKPACK_API_KEY or BACKPACK_API_SECRET not found in .env file or environment.")
        sys.exit(1)

    print("Initializing DefaultExecutionClient...")
    try:
        # Provide a default trading symbol, e.g., "SOL-USDC"
        # The query_balances function itself might not use this symbol,
        # but the constructor requires it.
        trading_symbol = "SOL_USDC_PERP" 
        client = exec_bridge.DefaultExecutionClient(api_key, api_secret, trading_symbol)
        print("DefaultExecutionClient initialized successfully.")
    except Exception as e:
        print(f"Error initializing DefaultExecutionClient: {e}")
        sys.exit(1)

    print("\nAttempting to query balances...")
    try:
        balances_json = client.query_balances()
        print("Successfully called query_balances.")
        print("Balances Response (JSON):")
        # The C++ side returns a nlohmann::json, which pybind11 converts to a Python dict/list
        import json
        print(json.dumps(balances_json, indent=4)) 
        
        # You can then access specific balances, e.g.:
        # if "USDC" in balances_json:
        #    print(f"USDC Balance: {balances_json['USDC']['available']}")

    except RuntimeError as e:
        print(f"RuntimeError calling query_balances: {e}")
    except Exception as e:
        print(f"An unexpected error occurred when calling query_balances: {e}")

if __name__ == "__main__":
    main()