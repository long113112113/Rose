#!/usr/bin/env python3
"""
Test program to measure mkoverlay completion times for all Corki skins
"""

import sys
import time
import random
from pathlib import Path
from typing import List, Tuple
import csv
import statistics

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from injection.manager import InjectionManager
from utils.paths import get_skins_dir
from utils.logging import setup_logging, get_logger

# Setup logging (reduce verbosity for cleaner output)
setup_logging(verbose=False)
log = get_logger()

class CorkiTimer:
    """Timer specifically for Corki skins"""
    
    def __init__(self):
        self.mkoverlay_times = []
        self.skin_names = []
    
    def log_mkoverlay_time(self, duration: float, skin: str):
        """Record mkoverlay completion time only"""
        self.mkoverlay_times.append(duration)
        self.skin_names.append(skin)
        print(f"[{len(self.mkoverlay_times):2d}] {skin:40s} | mkoverlay: {duration:.3f}s")

def find_corki_skins(base_dir: Path) -> List[Tuple[str, Path]]:
    """Find all Corki skins"""
    corki_skins = []
    corki_dir = base_dir / "Corki"
    if corki_dir.is_dir():
        for skin_zip in corki_dir.glob("*.zip"):
            corki_skins.append((skin_zip.stem, skin_zip))
    return corki_skins

def get_mkoverlay_timing(injection_manager) -> float:
    """Retrieve the last mkoverlay timing from the injector"""
    if injection_manager.injector and injection_manager.injector.last_injection_timing:
        return injection_manager.injector.last_injection_timing['mkoverlay_duration']
    return None

def run_corki_test():
    """Run the Corki skins injection performance test"""
    print("=" * 80)
    print("CORKI SKINS MKOVERLAY TIMING TEST")
    print("=" * 80)
    
    # Initialize injection manager
    print("Initializing injection system...")
    manager = InjectionManager()
    manager.initialize_when_ready()
    time.sleep(2)  # Give background thread time to initialize

    if not manager._initialized:
        print("ERROR: Injection system failed to initialize")
        return

    print("[OK] Injection system ready")

    skins_dir = get_skins_dir()
    actual_skins_dir = skins_dir / "skins"
    print(f"Scanning Corki skins directory: {actual_skins_dir}")

    corki_skins = find_corki_skins(actual_skins_dir)
    if not corki_skins:
        print("ERROR: No Corki skins found")
        return

    print(f"[OK] Found {len(corki_skins)} Corki skins")
    
    # Sort skins by name for consistent testing order
    corki_skins.sort(key=lambda x: x[0])

    print("\n" + "=" * 80)
    print("STARTING CORKI SKINS TESTS")
    print("=" * 80)
    
    timer = CorkiTimer()
    successful_injections = 0
    failed_injections = 0

    for i, (skin_name, skin_path) in enumerate(corki_skins):
        print(f"\n[{i+1:2d}/{len(corki_skins)}] Testing: {skin_name}")
        try:
            success = manager.inject_skin_for_testing(skin_name)
            
            if success:
                successful_injections += 1
                mkoverlay_time = get_mkoverlay_timing(manager)
                if mkoverlay_time is not None:
                    timer.log_mkoverlay_time(mkoverlay_time, skin_name)
                else:
                    print(f"    [WARN] Could not get mkoverlay timing")
            else:
                failed_injections += 1
                print(f"    [FAIL] Injection failed")
                
        except Exception as e:
            failed_injections += 1
            print(f"    [ERROR] Error: {e}")
        
        time.sleep(0.5)  # Small delay between injections

    print("\n" + "=" * 80)
    print("CORKI TEST RESULTS")
    print("=" * 80)
    print(f"Successful injections: {successful_injections}")
    print(f"Failed injections: {failed_injections}")
    print(f"Total Corki skins tested: {len(corki_skins)}")

    if timer.mkoverlay_times:
        times_list = timer.mkoverlay_times
        
        # Calculate statistics
        mean_time = statistics.mean(times_list)
        median_time = statistics.median(times_list)
        std_time = statistics.stdev(times_list) if len(times_list) > 1 else 0
        min_time = min(times_list)
        max_time = max(times_list)
        
        print(f"\nCorki Skins mkoverlay Timing Statistics:")
        print(f"  Mean: {mean_time:.3f}s")
        print(f"  Median: {median_time:.3f}s")
        print(f"  Std Dev: {std_time:.3f}s")
        print(f"  Min: {min_time:.3f}s")
        print(f"  Max: {max_time:.3f}s")

        # Rank skins by speed
        ranked_skins = sorted(zip(timer.skin_names, timer.mkoverlay_times), key=lambda x: x[1])
        print(f"\nCorki Skins Ranked by Speed (fastest to slowest):")
        print("-" * 70)
        for i, (skin, time_val) in enumerate(ranked_skins):
            print(f"{i+1:2d}. {skin:40s} | {time_val:.3f}s")

        # Create text-based histogram
        print(f"\nText-based Histogram (Corki mkoverlay timing):")
        histogram = {}
        bin_size = 0.1  # 0.1 second bins
        for time_val in times_list:
            bin_val = round(time_val / bin_size) * bin_size
            histogram[bin_val] = histogram.get(bin_val, 0) + 1
        
        for bin_val in sorted(histogram.keys()):
            count = histogram[bin_val]
            bar = "*" * (count * 50 // len(times_list))  # Scale to max 50 chars
            print(f"  {bin_val:4.1f}s: {count:2d} {bar}")
        
        # Save raw data
        data_path = Path("corki_mkoverlay_timing.csv")
        with open(data_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Skin", "mkoverlay_time"])
            for i, skin_name in enumerate(timer.skin_names):
                writer.writerow([skin_name, f"{timer.mkoverlay_times[i]:.3f}"])
        print(f"[OK] Corki timing data saved to: {data_path}")
    else:
        print("No successful injections to analyze")

if __name__ == "__main__":
    run_corki_test()
