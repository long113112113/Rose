#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tesseract OCR Installation Checker
Run this script to diagnose Tesseract OCR installation issues
"""

import sys
import os

# Add the parent directory to Python path so we can import our modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from utils.tesseract_path import print_installation_guide, get_tesseract_configuration, validate_tesseract_installation

def main():
    """Main diagnostic function"""
    print("LoL Skin Changer - Tesseract OCR Diagnostic Tool")
    print("=" * 60)
    
    # Get detailed configuration
    config = get_tesseract_configuration()
    
    print(f"Platform: {config['platform']}")
    print(f"Python: {sys.version}")
    print()
    
    # Check tesseract executable
    print("Tesseract Executable:")
    if config['tesseract_exe']:
        print(f"[OK] Found: {config['tesseract_exe']}")
        if os.path.isfile(config['tesseract_exe']):
            print("   File exists and is accessible")
        else:
            print("   [ERROR] File does not exist or is not accessible")
    else:
        print("[ERROR] Not found")
    
    print()
    
    # Check tessdata directory
    print("Tessdata Directory:")
    if config['tessdata_dir']:
        print(f"[OK] Found: {config['tessdata_dir']}")
        if os.path.isdir(config['tessdata_dir']):
            print("   Directory exists and is accessible")
            
            # List some language files
            lang_files = [f for f in os.listdir(config['tessdata_dir']) if f.endswith('.traineddata')]
            if lang_files:
                print(f"   Language files found: {len(lang_files)}")
                print(f"   Sample files: {', '.join(sorted(lang_files)[:5])}")
            else:
                print("   [ERROR] No language files (.traineddata) found")
        else:
            print("   [ERROR] Directory does not exist or is not accessible")
    else:
        print("[ERROR] Not found")
    
    print()
    
    # Check environment variables
    print("Environment Variables:")
    if config['environment']['TESSDATA_PREFIX']:
        print(f"[OK] TESSDATA_PREFIX: {config['environment']['TESSDATA_PREFIX']}")
    else:
        print("[ERROR] TESSDATA_PREFIX: Not set")
    
    print("PATH entries (first 10):")
    for i, path in enumerate(config['environment']['PATH'][:10]):
        print(f"   {i+1:2d}. {path}")
    if len(config['environment']['PATH']) > 10:
        print(f"   ... and {len(config['environment']['PATH']) - 10} more")
    
    print()
    
    # Validate installation
    print("Validation Results:")
    is_valid, errors = validate_tesseract_installation()
    
    if is_valid:
        print("[OK] Tesseract OCR installation is valid and ready to use!")
    else:
        print("[ERROR] Tesseract OCR installation has issues:")
        for error in errors:
            print(f"   - {error}")
    
    print()
    
    # Test tesserocr import
    print("Python Package Test:")
    try:
        import tesserocr
        print("[OK] tesserocr package is installed")
        print(f"   Version: {tesserocr.__version__ if hasattr(tesserocr, '__version__') else 'Unknown'}")
        
        # Try to create a basic API instance
        try:
            from tesserocr import PyTessBaseAPI
            api = PyTessBaseAPI(lang='eng')
            print("[OK] PyTessBaseAPI can be created successfully")
            api.End()
        except Exception as api_error:
            print(f"[ERROR] PyTessBaseAPI creation failed: {api_error}")
            
    except ImportError as import_error:
        print(f"[ERROR] tesserocr package not found: {import_error}")
        print("   Install with: pip install -r requirements.txt")
    
    print()
    print("=" * 60)
    
    # Show installation guide if there are issues
    if not is_valid:
        print_installation_guide()
    else:
        print("[SUCCESS] Everything looks good! Your Tesseract OCR installation should work with SkinCloner.")
        print("\nYou can now run the main application:")
        print("   python main.py")

if __name__ == "__main__":
    main()
