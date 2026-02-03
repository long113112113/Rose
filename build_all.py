#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Complete build script for Rose
Builds executable with PyInstaller and creates Windows installer in one step
"""

import sys
import subprocess
import time
from pathlib import Path


MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    sys.stderr.write(
        f"Rose build scripts require Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.\n"
        "Please re-run using an updated interpreter.\n"
    )
    sys.exit(1)


def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def print_step(step_num, total_steps, description):
    """Print a step description"""
    print(f"\n[Step {step_num}/{total_steps}] {description}")
    print("-" * 70)


def check_cargo_installed():
    """Check if Rust/Cargo is installed"""
    try:
        subprocess.run(["cargo", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_build_sidecar():
    """Build the Rust sidecar using cargo"""
    print_step(1, 4, "Building Rust Sidecar")
    
    sidecar_dir = Path("sidecar")
    if not sidecar_dir.exists():
        print("[ERROR] sidecar directory not found!")
        return False

    if not check_cargo_installed():
        print("[ERROR] Rust/Cargo not found! Please install Rust from https://rustup.rs/")
        return False

    print("Running 'cargo build --release' in sidecar directory...")
    try:
        result = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(sidecar_dir),
            capture_output=False,
            text=True
        )
        
        if result.returncode != 0:
            print("\n[ERROR] Sidecar build failed!")
            return False
            
        # Verify output
        sidecar_exe = sidecar_dir / "target" / "release" / "sidecar.exe"
        if not sidecar_exe.exists():
            print(f"\n[ERROR] Sidecar executable not found at {sidecar_exe}")
            return False
            
        print(f"\n[OK] Sidecar built successfully: {sidecar_exe}")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Failed to run cargo: {e}")
        return False


def run_build_exe():
    """Run the build_pyinstaller.py script"""
    print_step(2, 4, "Building Executable with PyInstaller")
    
    # Run build_pyinstaller.py as a subprocess
    result = subprocess.run(
        [sys.executable, "build_pyinstaller.py"],
        capture_output=False,  # Show output in real-time
        text=True
    )
    
    if result.returncode != 0:
        print("\n[ERROR] Executable build failed!")
        return False
    
    # Verify the executable was created
    exe_path = Path("dist/Rose/Rose.exe")
    if not exe_path.exists():
        print("\n[ERROR] Executable not found at expected location!")
        return False
    
    print("\n[OK] Executable build completed successfully!")
    return True


def run_create_installer():
    """Run the create_installer.py script"""
    print_step(3, 4, "Creating Windows Installer with Inno Setup")
    
    # Run create_installer.py as a subprocess
    result = subprocess.run(
        [sys.executable, "create_installer.py"],
        capture_output=False,  # Show output in real-time
        text=True
    )
    
    if result.returncode != 0:
        print("\n[ERROR] Installer creation failed!")
        return False
    
    # Verify the installer was created
    installer_dir = Path("installer")
    installer_files = list(installer_dir.glob("Rose_Setup*.exe"))
    if not installer_files:
        print("\n[ERROR] Installer not found at expected location!")
        return False
    
    print("\n[OK] Installer creation completed successfully!")
    return True


def check_dependencies():
    """Check if required dependencies are installed"""
    print_step(0, 4, "Verifying Dependencies")
    
    try:
        import requests
        print(f"\n[OK] Core dependencies detected")
        print("[INFO] Core dependencies ready")
        return True
    except ImportError as e:
        print(f"\n[ERROR] Missing dependency: {e}")
        print("\nPlease install dependencies:")
        print("  pip install -r requirements.txt")
        return False


def build_all():
    """Complete build process: executable + installer"""
    
    print_header("Rose - Complete Build Process")
    
    start_time = time.time()
    
    # Step 0: Check dependencies are installed
    if not check_dependencies():
        print_header("[FAILED] BUILD FAILED AT STEP 0/4")
        print("Required dependencies are missing.")
        print("\nTroubleshooting:")
        print("1. Install dependencies:")
        print("   pip install -r requirements.txt")
        print("2. Run the build again")
        return False
    
    # Step 1: Build Sidecar
    if not run_build_sidecar():
        print_header("[FAILED] BUILD FAILED AT STEP 1/4")
        print("Sidecar build failed.")
        return False

    # Step 2: Build executable
    if not run_build_exe():
        print_header("[FAILED] BUILD FAILED AT STEP 2/4")
        print("The executable build failed. Please check the errors above.")
        print("\nTroubleshooting:")
        print("1. Make sure all dependencies are installed:")
        print("   pip install -r requirements.txt")
        print("2. Close any running instances of Rose.exe")
        print("3. Make sure PyInstaller is installed:")
        print("   pip install pyinstaller")
        return False
    
    # Step 3: Create installer
    if not run_create_installer():
        print_header("[WARNING] BUILD PARTIALLY COMPLETED (3/4)")
        print("Executable was built successfully, but installer creation failed.")
        print("\nYou can still use the executable directly from:")
        print("  dist/Rose/Rose.exe")
        print("\nTo create the installer:")
        print("1. Install Inno Setup from: https://jrsoftware.org/isdl.php")
        print("2. Run: python create_installer.py")
        return False
    
    # Success!
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)
    
    print_header("[SUCCESS] BUILD COMPLETED SUCCESSFULLY!")
    
    # Get file information
    exe_path = Path("dist/Rose/Rose.exe")
    installer_files = list(Path("installer").glob("Rose_Setup*.exe"))
    installer_path = installer_files[0] if installer_files else None
    
    exe_size_mb = exe_path.stat().st_size / (1024 * 1024)
    
    print("Build Summary:")
    print(f"  Time elapsed: {minutes}m {seconds}s")
    print()
    print("Generated Files:")
    print(f"  [OK] Executable:  {exe_path}")
    print(f"    Size: {exe_size_mb:.1f} MB")
    
    if installer_path:
        installer_size_mb = installer_path.stat().st_size / (1024 * 1024)
        print(f"  [OK] Installer:   {installer_path}")
        print(f"    Size: {installer_size_mb:.1f} MB")
    
    print("\nNext Steps:")
    print("  • For development/testing:")
    print("    Run: dist\\Rose\\Rose.exe")
    print()
    print("  • For distribution:")
    print(f"    Share: {installer_path if installer_path else 'installer/Rose_Setup.exe'}")
    print()
    print("  • For portable version:")
    print("    Zip: dist\\Rose\\ folder")
    
    print("\n" + "=" * 70)
    
    return True


def main():
    """Main entry point"""
    
    # Check if we're in the right directory
    if not Path("main.py").exists():
        print("ERROR: main.py not found!")
        print("Please run this script from the Rose root directory.")
        sys.exit(1)
    
    # Check if build_pyinstaller.py exists
    if not Path("build_pyinstaller.py").exists():
        print("ERROR: build_pyinstaller.py not found!")
        sys.exit(1)
    
    # Check if create_installer.py exists
    if not Path("create_installer.py").exists():
        print("ERROR: create_installer.py not found!")
        sys.exit(1)
    
    # Run the complete build
    success = build_all()
    
    if not success:
        sys.exit(1)
    


if __name__ == "__main__":
    main()

