#!/usr/bin/env python3
"""
Simple plotting script for injection timing data
Run this after test_injection_performance.py to create visualizations
"""

import sys
from pathlib import Path

try:
    import pandas as pd
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError as e:
    print(f"Required packages not available: {e}")
    print("Please install: pip install pandas matplotlib numpy")
    sys.exit(1)

def plot_injection_timing():
    """Plot histogram and statistics from injection timing data"""
    
    data_path = Path("injection_performance_data.csv")
    if not data_path.exists():
        print(f"Data file not found: {data_path}")
        print("Please run test_injection_performance.py first")
        return
    
    # Load data
    df = pd.read_csv(data_path)
    
    print("Loading injection timing data...")
    print(f"Found {len(df)} successful injections")
    
    # Calculate statistics
    times = df['mkoverlay_time']
    stats = times.describe()
    
    print("\nStatistics:")
    print(stats)
    
    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # Histogram
    ax1.hist(times, bins=20, alpha=0.7, edgecolor='black', color='skyblue')
    ax1.set_xlabel('mkoverlay Completion Time (seconds)')
    ax1.set_ylabel('Frequency')
    ax1.set_title('Distribution of Injection Times (mkoverlay completion)')
    ax1.grid(True, alpha=0.3)
    
    # Add statistics text
    stats_text = f'Mean: {stats["mean"]:.3f}s\nMedian: {stats["50%"]:.3f}s\nStd: {stats["std"]:.3f}s'
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, 
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    # Box plot
    ax2.boxplot(times, vert=True, patch_artist=True, 
                boxprops=dict(facecolor='lightblue', alpha=0.7))
    ax2.set_ylabel('mkoverlay Completion Time (seconds)')
    ax2.set_title('Box Plot of Injection Times')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save plot
    plot_path = Path("injection_performance_histogram.png")
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    print(f"\n✓ Histogram saved to: {plot_path}")
    
    # Show plot
    plt.show()
    
    # Create champion-specific analysis
    champion_stats = df.groupby('Champion')['mkoverlay_time'].agg(['count', 'mean', 'std', 'min', 'max'])
    champion_stats = champion_stats.sort_values('mean')
    
    print(f"\nChampion-specific timing (top 10 fastest):")
    print(champion_stats.head(10).round(3))
    
    print(f"\nChampion-specific timing (top 10 slowest):")
    print(champion_stats.tail(10).round(3))
    
    # Save champion analysis
    champion_path = Path("champion_timing_analysis.csv")
    champion_stats.to_csv(champion_path)
    print(f"\n✓ Champion analysis saved to: {champion_path}")

if __name__ == "__main__":
    plot_injection_timing()
