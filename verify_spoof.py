import sys
import os
import time

# Add current directory to path
sys.path.append(os.getcwd())

from lcu import LCU

def main():
    print("Initializing LCU...")
    lcu = LCU()
    
    print("Connecting to LCU...")
    lcu.refresh_if_needed()
    
    if not lcu.ok:
        print("LCU not connected. Please start League Client.")
        return

    print(f"Connected to LCU at port {lcu.port}")
    
    print("Attempting to spoof rank...")
    # Default parameters: CHALLENGER I
    resp = lcu._properties.spoof_rank()
    
    if resp:
        print(f"Success! Response: {resp}")
    else:
        print("Failed to spoof rank (no response or error).")

if __name__ == "__main__":
    main()
