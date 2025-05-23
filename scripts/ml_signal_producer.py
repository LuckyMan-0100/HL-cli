import json
import random
import time
import os
import uuid
from dotenv import load_dotenv
import signal # Import signal for graceful shutdown

# Load environment variables from .env file
load_dotenv()

# Global flag to control the main loop
running = True

def shutdown_handler(signum, frame):
    """Handles termination signals."""
    global running
    print(f"Received signal {signum}, shutting down gracefully...")
    running = False

# Register signal handlers
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

def generate_signal_and_save(file_path="signal.json"):
    """Generates a trading signal and saves it to a JSON file."""
    try:
        # Simulate ML model output for buy/sell signal and confidence
        signal_type = random.choice(["buy", "sell"])
        confidence = random.uniform(0.6, 1.0)  # Confidence between 0.6 and 1.0

        # Get current timestamp
        timestamp = int(time.time() * 1000)

        # ------------ NEW QUANTITY LOGIC FOR SOL_USDC_PERP -------------
        # Values from Backpack Exchange API for SOL_USDC_PERP:
        # minQuantity: 0.01
        # stepSize: 0.01
        min_allowable_qty = 0.01
        qty_step_size = 0.01
        
        # Determine the number of decimal places from stepSize
        decimal_places = 0
        if "." in str(qty_step_size):
            decimal_places = len(str(qty_step_size).split('.')[1])

        # Generate a base random quantity, e.g., between 1x and 10x the minimum
        # (Adjust range as needed for more realistic testing)
        # Ensure it is a multiple of qty_step_size by generating a multiplier for the step size
        # Example: generate between 1 step and 100 steps (0.01 to 1.0 for SOL_USDC_PERP)
        num_min_steps = int(min_allowable_qty / qty_step_size)
        # Ensure we generate at least the minimum number of steps
        # Let's aim for quantities between min_allowable_qty and, say, 0.5 SOL
        max_qty_target = 0.5 
        num_max_steps = int(max_qty_target / qty_step_size)
        
        random_steps = random.randint(num_min_steps, num_max_steps)
        qty = random_steps * qty_step_size
        
        # Format to required decimal places, ensuring it's a string
        qty_str = f"{qty:.{decimal_places}f}"


        # More realistic stop loss, e.g. .35-.85%
        stop_loss_percentage = random.uniform(0.0035, 0.0085)
        
        # REMOVED SIMULATED PRICE AND STOP_LOSS_TRIGGER_PRICE CALCULATION
        # The following block has been removed:
        # # Simulate a current price - replace with actual price fetching if possible
        # # For SOL_USDC_PERP, let's assume a price around $100 for calculation
        # # This is only for calculating a somewhat realistic stop_loss_trigger_price
        # # The actual order execution will use the current market price.
        # # Fetching actual price would be ideal here if this were a live system.
        # try:
        #     # Attempt to get a simulated price from an environment variable if set
        #     simulated_current_price = float(os.getenv("SIMULATED_PRICE", "170.00"))
        # except ValueError:
        #     simulated_current_price = 170.00 # Default if not set or invalid

        # if signal_type == "buy":
        #     stop_loss_trigger_price = simulated_current_price * (1 - stop_loss_percentage)
        # else:  # sell
        #     stop_loss_trigger_price = simulated_current_price * (1 + stop_loss_percentage)
        # 
        # # Ensure stop_loss_trigger_price is also formatted to the exchange's tick_size requirement
        # # Assuming tick_size for SOL_USDC_PERP price is 0.01 (from previous API call)
        # price_tick_size = 0.01 
        # price_decimal_places = 0
        # if "." in str(price_tick_size):
        #     price_decimal_places = len(str(price_tick_size).split('.')[1])
        # 
        # stop_loss_trigger_price_str = f"{stop_loss_trigger_price:.{price_decimal_places}f}"


        signal_data = {
            "signal_id": str(uuid.uuid4()),
            "timestamp": timestamp,
            "symbol": os.getenv("TRADING_SYMBOL", "SOL_USDC_PERP"),  # Use TRADING_SYMBOL from .env
            "signal_type": signal_type,
            "confidence": round(confidence, 4),
            "order_quantity_config": {
                "type": "Market",  # Can be "Market" or "Limit"
                #"price": None, # Specify for "Limit" orders
                "quantity_usd": None,  # USD value of the order (optional, for ML model to decide)
                "quantity": qty_str,  # Base asset quantity (e.g. SOL)
                #"leverage": None # Leverage is usually account-wide for PERPs
            },
            "conditional_order_params": {
                # "stop_loss_trigger_price": stop_loss_trigger_price_str, # REMOVED
                #"take_profit_trigger_price": None # Optional
            }
        }

        with open(file_path, 'w') as f:
            json.dump(signal_data, f, indent=4)
        
        print(f"Generated signal: Type: {signal_type}, Qty: {qty_str}, Conf: {confidence:.2f}") # Removed SL from print
        print(f"Trading signal saved to {os.path.abspath(file_path)}")
        return signal_data

    except Exception as e:
        print(f"Error generating or saving signal: {e}")
        return None

if __name__ == "__main__":
    # Determine the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Based on run_paper_trading.py, it seems to expect it at the root of HL-cli.
    project_root = os.path.dirname(script_dir) # Moves one level up from scripts/
    signal_file = os.path.join(project_root, "signal.json")

    print(f"ML Signal Producer started. Saving signals to: {signal_file}")
    print("Running in loop, press Ctrl+C to stop.")

    while running:
        print(f"Generating new signal...")
        generate_signal_and_save(file_path=signal_file)
        
        # Wait for a few seconds before generating the next signal
        # Check running flag frequently during sleep to allow faster shutdown
        for _ in range(5): # Check every second for 5 seconds
            if not running:
                break
            time.sleep(1)
    
    print("ML Signal Producer stopped.") 