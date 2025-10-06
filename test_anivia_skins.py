#!/usr/bin/env python3
"""
Test program to measure mkoverlay timing for all Anivia skins
"""

import sys
import time
import random
from pathlib import Path
from typing import List, Tuple

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from injection.manager import InjectionManager
from utils.paths import get_skins_dir
from utils.logging import setup_logging, get_logger

# Setup logging (reduce verbosity for cleaner output)
setup_logging(verbose=False)
log = get_logger()

class AniviaTimer:
    """Timer specifically for Anivia skins"""
    
    def __init__(self):
        self.mkoverlay_times = []
        self.skin_names = []
    
    def log_mkoverlay_time(self, duration: float, skin: str):
        """Record mkoverlay completion time for Anivia skin"""
        self.mkoverlay_times.append(duration)
        self.skin_names.append(skin)
        print(f"[{len(self.mkoverlay_times):2d}] {skin:30s} | mkoverlay: {duration:.3f}s")

def find_anivia_skins(skins_dir: Path) -> List[Tuple[str, Path]]:
    """Find all Anivia skins"""
    anivia_skins = []
    anivia_dir = skins_dir / "Anivia"
    
    if not anivia_dir.exists():
        print(f"[ERROR] Anivia directory not found: {anivia_dir}")
        return anivia_skins
    
    for skin_zip in anivia_dir.glob("*.zip"):
        skin_name = skin_zip.stem
        anivia_skins.append((skin_name, skin_zip))
    
    return sorted(anivia_skins)

def get_mkoverlay_timing(injection_manager) -> float:
    """Get mkoverlay timing from the last injection"""
    if injection_manager.injector and injection_manager.injector.last_injection_timing:
        return injection_manager.injector.last_injection_timing['mkoverlay_duration']
    return None

def run_anivia_test():
    """Run the Anivia skins injection test"""
    print("=" * 80)
    print("ANIVIA SKINS MKOVERLAY TIMING TEST")
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
    
    # Find Anivia skins
    skins_dir = get_skins_dir()
    actual_skins_dir = skins_dir / "skins"
    print(f"Scanning Anivia skins directory: {actual_skins_dir}")
    
    anivia_skins = find_anivia_skins(actual_skins_dir)
    if not anivia_skins:
        print("ERROR: No Anivia skins found")
        return
    
    print(f"[OK] Found {len(anivia_skins)} Anivia skins")
    
    print("\n" + "=" * 80)
    print("STARTING ANIVIA SKINS TESTS")
    print("=" * 80)
    
    timer = AniviaTimer()
    successful_injections = 0
    failed_injections = 0
    
    for i, (skin_name, skin_path) in enumerate(anivia_skins):
        print(f"\n[{i+1:2d}/{len(anivia_skins)}] Testing: {skin_name}")
        
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
        
        # Small delay between injections
        time.sleep(0.5)
    
    print("\n" + "=" * 80)
    print("ANIVIA TEST RESULTS")
    print("=" * 80)
    print(f"Successful injections: {successful_injections}")
    print(f"Failed injections: {failed_injections}")
    print(f"Total Anivia skins tested: {len(anivia_skins)}")
    
    if timer.mkoverlay_times:
        times_list = timer.mkoverlay_times
        
        # Calculate statistics
        mean_time = sum(times_list) / len(times_list)
        median_time = sorted(times_list)[len(times_list) // 2]
        min_time = min(times_list)
        max_time = max(times_list)
        
        # Calculate standard deviation
        variance = sum((x - mean_time) ** 2 for x in times_list) / len(times_list)
        std_time = variance ** 0.5
        
        print(f"\nAnivia Skins mkoverlay Timing Statistics:")
        print(f"  Mean: {mean_time:.3f}s")
        print(f"  Median: {median_time:.3f}s")
        print(f"  Std Dev: {std_time:.3f}s")
        print(f"  Min: {min_time:.3f}s")
        print(f"  Max: {max_time:.3f}s")
        
        # Sort by time for ranking
        skin_times = list(zip(timer.skin_names, timer.mkoverlay_times))
        skin_times.sort(key=lambda x: x[1])
        
        print(f"\nAnivia Skins Ranked by Speed (fastest to slowest):")
        print("-" * 60)
        for i, (skin_name, time_val) in enumerate(skin_times, 1):
            print(f"{i:2d}. {skin_name:30s} | {time_val:.3f}s")
        
        # Create simple text-based histogram
        print(f"\nText-based Histogram (Anivia mkoverlay timing):")
        histogram = {}
        for time_val in times_list:
            bin_val = round(time_val, 1)
            histogram[bin_val] = histogram.get(bin_val, 0) + 1
        
        for bin_val in sorted(histogram.keys()):
            count = histogram[bin_val]
            bar = "*" * (count * 40 // len(times_list))  # Scale to max 40 chars
            print(f"  {bin_val:4.1f}s: {count:2d} {bar}")
        
        # Save Anivia-specific data
        data_path = Path("anivia_mkoverlay_timing.csv")
        with open(data_path, 'w') as f:
            f.write("Skin,mkoverlay_time\n")
            for skin_name, time_val in zip(timer.skin_names, timer.mkoverlay_times):
                f.write(f"{skin_name},{time_val:.3f}\n")
        print(f"\n[OK] Anivia timing data saved to: {data_path}")
        
    else:
        print("No successful injections to analyze")

if __name__ == "__main__":
    run_anivia_test()
