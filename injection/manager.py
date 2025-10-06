#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injection Manager
Manages the injection process and coordinates with OCR system
"""

import time
import threading
from pathlib import Path
from typing import Optional

from .injector import SkinInjector
from utils.logging import get_logger
from constants import INJECTION_THRESHOLD_SECONDS

log = get_logger()


class InjectionManager:
    """Manages skin injection with automatic triggering"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir
        self.zips_dir = zips_dir
        self.game_dir = game_dir
        self.injector = None  # Will be initialized lazily
        self.last_skin_name = None
        self.last_injection_time = 0.0
        self.injection_threshold = INJECTION_THRESHOLD_SECONDS
        self.injection_lock = threading.Lock()
        self._initialized = False
    
    def _ensure_initialized(self):
        """Initialize the injector lazily when first needed"""
        if not self._initialized:
            with self.injection_lock:
                if not self._initialized:  # Double-check inside lock
                    log.info("[INJECT] Initializing injection system...")
                    self.injector = SkinInjector(self.tools_dir, self.mods_dir, self.zips_dir, self.game_dir)
                    self._initialized = True
                    log.info("[INJECT] Injection system initialized successfully")
        
    def update_skin(self, skin_name: str):
        """Update the current skin and potentially trigger injection"""
        if not skin_name:
            return
        
        self._ensure_initialized()
            
        with self.injection_lock:
            current_time = time.time()
            
            # If skin changed or enough time passed, trigger injection
            if (skin_name != self.last_skin_name or 
                current_time - self.last_injection_time >= self.injection_threshold):
                
                log.info(f"[INJECT] Starting injection for: {skin_name}")
                injection_start_time = time.time()
                success = self.injector.inject_skin(skin_name)
                
                # Note: The actual injection work duration is logged by the injector itself
                # This duration includes the full process including runoverlay runtime
                total_duration = time.time() - injection_start_time
                
                if success:
                    self.last_skin_name = skin_name
                    self.last_injection_time = current_time
                    log.info(f"[INJECT] Successfully injected: {skin_name} (total process: {total_duration:.2f}s)")
                else:
                    log.error(f"[INJECT] Failed to inject: {skin_name} (total process: {total_duration:.2f}s)")
    
    def inject_skin_immediately(self, skin_name: str, stop_callback=None) -> bool:
        """Immediately inject a specific skin"""
        self._ensure_initialized()
        
        with self.injection_lock:
            log.info(f"[INJECT] Immediate injection for: {skin_name}")
            injection_start_time = time.time()
            success = self.injector.inject_skin(skin_name, stop_callback=stop_callback)
            
            # Note: The actual injection work duration is logged by the injector itself
            # This duration includes the full process including runoverlay runtime
            total_duration = time.time() - injection_start_time
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
                log.info(f"[INJECT] Immediate injection successful: {skin_name} (total process: {total_duration:.2f}s)")
            else:
                log.error(f"[INJECT] Immediate injection failed: {skin_name} (total process: {total_duration:.2f}s)")
            return success
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing purposes - stops overlay immediately after mkoverlay"""
        if not skin_name:
            return False
            
        self._ensure_initialized()
        with self.injection_lock:
            log.info(f"[INJECT] Test injection for: {skin_name}")
            injection_start_time = time.time()
            
            # Use the injector's method that stops overlay after mkoverlay
            success = self.injector.inject_skin_for_testing(skin_name)
            
            total_duration = time.time() - injection_start_time
            
            if success:
                self.last_skin_name = skin_name
                self.last_injection_time = time.time()
                log.info(f"[INJECT] Test injection successful: {skin_name} (total process: {total_duration:.2f}s)")
            else:
                log.error(f"[INJECT] Test injection failed: {skin_name} (total process: {total_duration:.2f}s)")
            return success
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        if not self._initialized:
            return True  # Nothing to clean if not initialized
        
        with self.injection_lock:
            return self.injector.clean_system()
    
    def initialize_when_ready(self):
        """Initialize the injection system when the app is ready (skins downloaded)"""
        if not self._initialized:
            log.info("[INJECT] App ready - initializing injection system in background...")
            # Initialize in a separate thread to avoid blocking
            import threading
            def init_thread():
                try:
                    self._ensure_initialized()
                    log.info("[INJECT] Background initialization completed - injection system ready")
                except Exception as e:
                    log.error(f"[INJECT] Background initialization failed: {e}")
            
            threading.Thread(target=init_thread, daemon=True).start()
    
    def get_last_injected_skin(self) -> Optional[str]:
        """Get the last successfully injected skin"""
        return self.last_skin_name
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if not self._initialized:
            return  # Nothing to stop if not initialized
            
        try:
            self.injector.stop_overlay_process()
        except Exception as e:
            log.warning(f"Injection: Failed to stop overlay process: {e}")
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        if not self._initialized:
            return  # Nothing to kill if not initialized
            
        try:
            self.injector.kill_all_runoverlay_processes()
        except Exception as e:
            log.warning(f"Injection: Failed to kill runoverlay processes: {e}")