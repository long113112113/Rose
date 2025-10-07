#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSLOL Skin Injector
Handles the actual skin injection using CSLOL tools
"""

import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional
import zipfile
import shutil

from utils.logging import get_logger
from utils.paths import get_skins_dir, get_injection_dir
from constants import PROCESS_TERMINATE_TIMEOUT_S, PROCESS_MONITOR_SLEEP_S, ENABLE_PRIORITY_BOOST, ENABLE_GAME_THROTTLE, ENABLE_GAME_SUSPENSION

log = get_logger()


class SkinInjector:
    """CSLOL-based skin injector"""
    
    def __init__(self, tools_dir: Path = None, mods_dir: Path = None, zips_dir: Path = None, game_dir: Optional[Path] = None):
        # Use injection folder as base if paths not provided
        injection_dir = Path(__file__).parent
        self.tools_dir = tools_dir or injection_dir / "tools"
        # Use user data directory for mods and skins to avoid permission issues
        self.mods_dir = mods_dir or get_injection_dir() / "mods"
        self.zips_dir = zips_dir or get_skins_dir()
        self.game_dir = game_dir or self._detect_game_dir()
        
        # Create directories if they don't exist
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        self.zips_dir.mkdir(parents=True, exist_ok=True)
        
        # Track current overlay process
        self.current_overlay_process = None
        
        # Store last injection timing data
        self.last_injection_timing = None
        
        # Check for CSLOL tools
        self._download_cslol_tools()
        
    def _detect_game_dir(self) -> Path:
        """Auto-detect League of Legends Game directory"""
        candidates = [
            Path(r"C:\Riot Games\League of Legends\Game"),
            Path(r"C:\Riot Games\League of Legends"),
            Path(r"C:\Program Files\Riot Games\League of Legends\Game"),
            Path(r"C:\Program Files (x86)\Riot Games\League of Legends\Game"),
        ]

        for c in candidates:
            if c.is_dir():
                exe = c / "League of Legends.exe"
                if exe.exists():
                    if c.name.lower() != "game" and (c / "Game" / "League of Legends.exe").exists():
                        gd = c / "Game"
                        log.info(f"Injector: Auto-detected game directory: {gd}")
                        return gd
                    log.info(f"Injector: Auto-detected game directory: {c}")
                    return c if c.name.lower() == "game" else (c / "Game")

        # Last resort: return default
        gd = Path(r"C:\Riot Games\League of Legends\Game")
        log.info(f"Injector: Using default game directory: {gd}")
        return gd
    
    def _download_cslol_tools(self):
        """Download CSLOL tools if not present"""
        required_tools = [
            "mod-tools.exe",
            "cslol-diag.exe", 
            "cslol-dll.dll",
            "wad-extract.exe",
            "wad-make.exe"
        ]
        
        missing_tools = []
        for tool in required_tools:
            if not (self.tools_dir / tool).exists():
                missing_tools.append(tool)
        
        if missing_tools:
            log.warning(f"Missing CSLOL tools: {missing_tools}")
            log.warning("Please download CSLOL tools manually and place them in injection/tools/")
            log.warning("Download from: https://github.com/CommunityDragon/CDTB")
            return False
        
        return True
    
    def _detect_tools(self) -> Dict[str, Path]:
        """Detect CSLOL tools"""
        tools = {
            "diag": self.tools_dir / "cslol-diag.exe",
            "modtools": self.tools_dir / "mod-tools.exe",
        }
        for name, exe in tools.items():
            if not exe.exists():
                log.error(f"[INJECTOR] Missing tool: {exe}")
        return tools
    
    def _resolve_zip(self, zip_arg: str) -> Path | None:
        """Resolve a ZIP by name or path with fuzzy matching"""
        cand = Path(zip_arg)
        if cand.exists():
            return cand

        self.zips_dir.mkdir(parents=True, exist_ok=True)

        def _norm(s: str) -> str:
            return "".join(ch.lower() for ch in s if ch.isalnum())

        target = zip_arg
        target_lower = target.lower()
        target_norm = _norm(target)

        all_zips = list(self.zips_dir.rglob("*.zip"))

        if not all_zips:
            return None

        # 1) exact filename (case-insensitive)
        for zp in all_zips:
            if zp.name.lower() == target_lower:
                return zp

        # 2) exact normalized match
        norm_map = {zp: _norm(zp.name) for zp in all_zips}
        exact_norm = [zp for zp, nz in norm_map.items() if nz == target_norm]
        if len(exact_norm) == 1:
            return exact_norm[0]

        # 3) contains normalized
        contains = [zp for zp, nz in norm_map.items() if target_norm and target_norm in nz]
        if len(contains) == 1:
            return contains[0]

        # 4) fuzzy best match
        try:
            import difflib
            best, best_score = None, 0.0
            for zp, nz in norm_map.items():
                score = difflib.SequenceMatcher(None, nz, target_norm).ratio()
                if target_norm and target_norm in nz:
                    score += 0.15
                if score > best_score:
                    best, best_score = zp, score
            return best
        except Exception:
            return None
    
    def _clean_mods_dir(self):
        """Clean the mods directory"""
        if not self.mods_dir.exists():
            self.mods_dir.mkdir(parents=True, exist_ok=True)
            return
        for p in self.mods_dir.iterdir():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except Exception:
                    pass
    
    def _clean_overlay_dir(self):
        """Clean the overlay directory to prevent file lock issues"""
        overlay_dir = self.mods_dir.parent / "overlay"
        if overlay_dir.exists():
            try:
                shutil.rmtree(overlay_dir, ignore_errors=True)
                log.debug("Injector: Cleaned overlay directory")
            except Exception as e:
                log.warning(f"Injector: Failed to clean overlay directory: {e}")
        overlay_dir.mkdir(parents=True, exist_ok=True)
    
    def _extract_zip_to_mod(self, zp: Path) -> Path:
        """Extract ZIP to mod directory"""
        target = self.mods_dir / zp.stem
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(target)
        log.info(f"Injector: Extracted {zp.name} -> {target}")
        return target
    
    def _mk_run_overlay(self, mod_names: List[str], timeout: int = 60, stop_callback=None) -> int:
        """Create and run overlay"""
        tools = self._detect_tools()
        exe = tools.get("modtools")
        if not exe or not exe.exists():
            log.error(f"[INJECTOR] Missing mod-tools.exe in {self.tools_dir}")
            return 127
            
        # Use overlay directory (should already be clean from _clean_overlay_dir)
        overlay_dir = self.mods_dir.parent / "overlay"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        
        names_str = "/".join(mod_names)
        gpath = str(self.game_dir)

        # Create overlay (this is the actual injection work)
        cmd = [
            str(exe), "mkoverlay", str(self.mods_dir), str(overlay_dir),
            f"--game:{gpath}", f"--mods:{names_str}", "--noTFT"
        ]
        
        log.debug(f"Injector: Creating overlay: {' '.join(cmd)}")
        mkoverlay_start = time.time()
        try:
            # Hide console window on Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
            
            # Boost process priority to maximize CPU contention if enabled
            if ENABLE_PRIORITY_BOOST:
                try:
                    import psutil
                    p = psutil.Process(proc.pid)
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                    log.debug(f"Injector: Boosted mkoverlay process priority (PID={proc.pid})")
                except Exception as e:
                    log.debug(f"Injector: Could not boost process priority: {e}")
            
            stdout, _ = proc.communicate(timeout=timeout)
            mkoverlay_duration = time.time() - mkoverlay_start
            
            if proc.returncode != 0:
                log.error(f"Injector: mkoverlay failed: {stdout}")
                return proc.returncode
            else:
                log.info(f"Injector: mkoverlay completed in {mkoverlay_duration:.2f}s - injection applied, game can start")
                # Store timing data for external access
                self.last_injection_timing = {
                    'mkoverlay_duration': mkoverlay_duration,
                    'timestamp': time.time()
                }
        except subprocess.TimeoutExpired:
            log.error("Injector: mkoverlay timeout")
            return 124
        except Exception as e:
            log.error(f"Injector: mkoverlay error: {e}")
            return 1

        # Run overlay
        cfg = overlay_dir / "cslol-config.json"
        cmd = [
            str(exe), "runoverlay", str(overlay_dir), str(cfg),
            f"--game:{gpath}", "--opts:configless"
        ]
        
        log.info(f"Injector: Running overlay: {' '.join(cmd)}")
        
        try:
            # Hide console window on Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
            
            # Boost process priority to maximize CPU contention if enabled
            if ENABLE_PRIORITY_BOOST:
                try:
                    import psutil
                    p = psutil.Process(proc.pid)
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                    log.debug(f"Injector: Boosted runoverlay process priority (PID={proc.pid})")
                except Exception as e:
                    log.debug(f"Injector: Could not boost process priority: {e}")
            
            self.current_overlay_process = proc
            
            # Monitor process with stop callback
            start_time = time.time()
            runoverlay_hooked = False
            while proc.poll() is None:
                # Check if we should stop (game ended)
                if stop_callback and stop_callback():
                    log.info("Injector: Game ended, stopping overlay process")
                    runoverlay_hooked = True  # Assume it hooked if game ended
                    proc.terminate()
                    try:
                        proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self.current_overlay_process = None
                    return 0  # Success - overlay ran through game
                
                # Check timeout
                if time.time() - start_time > timeout:
                    log.warning(f"Injector: runoverlay timeout after {timeout}s - may not have hooked in time")
                    proc.terminate()
                    try:
                        proc.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self.current_overlay_process = None
                    return 1  # Timeout = likely failed to hook
                
                time.sleep(PROCESS_MONITOR_SLEEP_S)
            
            # Process completed normally
            stdout, _ = proc.communicate()
            self.current_overlay_process = None
            if proc.returncode != 0:
                log.error(f"Injector: runoverlay failed: {stdout}")
                return proc.returncode
            else:
                log.debug(f"Injector: runoverlay completed successfully")
                return 0
        except Exception as e:
            log.error(f"Injector: runoverlay error: {e}")
            return 1
    
    def _mk_overlay_only(self, mod_names: List[str], timeout: int = 60) -> int:
        """Create overlay using mkoverlay only (no runoverlay) - for testing"""
        try:
            # Build mkoverlay command
            cmd = [
                str(self.tools_dir / "mod-tools.exe"),
                "mkoverlay",
                str(self.mods_dir),
                str(self.mods_dir.parent / "overlay"),
                f"--game:{self.game_dir}",
                f"--mods:{','.join(mod_names)}",
                "--noTFT"
            ]
            
            log.debug(f"Injector: Creating overlay (mkoverlay only): {' '.join(cmd)}")
            mkoverlay_start = time.time()
            
            # Set creation flags for Windows
            import sys
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
                stdout, _ = proc.communicate(timeout=timeout)
                mkoverlay_duration = time.time() - mkoverlay_start
                
                if proc.returncode != 0:
                    log.error(f"Injector: mkoverlay failed: {stdout}")
                    return proc.returncode
                else:
                    log.debug(f"Injector: mkoverlay completed in {mkoverlay_duration:.2f}s")
                    self.last_injection_timing = {
                        'mkoverlay_duration': mkoverlay_duration,
                        'timestamp': time.time()
                    }
                    return 0
                    
            except subprocess.TimeoutExpired:
                log.error(f"Injector: mkoverlay timed out after {timeout}s")
                proc.kill()
                return -1
            except Exception as e:
                log.error(f"Injector: mkoverlay failed with exception: {e}")
                return -1
                
        except Exception as e:
            log.error(f"Injector: Failed to create mkoverlay command: {e}")
            return -1
    
    def inject_skin(self, skin_name: str, timeout: int = 60, stop_callback=None) -> bool:
        """Inject a single skin"""
        injection_start_time = time.time()
        game_process_throttled = None
        game_process_suspended = None
        
        # Find the skin ZIP
        zp = self._resolve_zip(skin_name)
        if not zp:
            log.error(f"Injector: Skin '{skin_name}' not found in {self.zips_dir}")
            avail = list(self.zips_dir.rglob('*.zip'))
            if avail:
                log.info("Injector: Available skins (first 10):")
                for a in avail[:10]:
                    log.info(f"  - {a.name}")
            return False
        
        log.debug(f"Injector: Using skin file: {zp}")
        
        # Start game process monitor thread if delay strategies enabled
        game_monitor_active = False
        if ENABLE_GAME_THROTTLE or ENABLE_GAME_SUSPENSION:
            import threading
            game_monitor_active = True
            
            def monitor_and_throttle_game():
                """Monitor for game process and throttle it when it starts"""
                try:
                    import psutil
                    import time
                    
                    log.info("GameMonitor: Started - waiting for League of Legends.exe...")
                    
                    # DEBUG: List all League-related processes currently running
                    league_procs = []
                    for p in psutil.process_iter(['name', 'pid']):
                        if 'league' in p.info['name'].lower():
                            league_procs.append(f"{p.info['name']} (PID={p.info['pid']})")
                    if league_procs:
                        log.info(f"GameMonitor: Current League processes: {', '.join(league_procs)}")
                    else:
                        log.info("GameMonitor: No League processes running yet")
                    
                    max_wait = 20.0  # Wait up to 20 seconds for game to start
                    start_wait = time.time()
                    check_count = 0
                    
                    while time.time() - start_wait < max_wait and game_monitor_active:
                        check_count += 1
                        found_game = False
                        
                        # Log every 2 seconds to show we're checking
                        if check_count % 40 == 0:  # Every 2 seconds (40 * 50ms)
                            elapsed = time.time() - start_wait
                            log.info(f"GameMonitor: Still waiting for game process... ({elapsed:.1f}s elapsed)")
                        
                        for proc in psutil.process_iter(['name', 'pid']):
                            if proc.info['name'] == 'League of Legends.exe':
                                try:
                                    game_proc = psutil.Process(proc.info['pid'])
                                    found_game = True
                                    
                                    log.info(f"GameMonitor: ✓ FOUND League of Legends.exe (PID={proc.info['pid']})")
                                    
                                    # Check process status before attempting to modify it
                                    proc_status = game_proc.status()
                                    log.info(f"GameMonitor: Process status: {proc_status}")
                                    
                                    if ENABLE_GAME_SUSPENSION:
                                        try:
                                            game_proc.suspend()
                                            nonlocal game_process_suspended
                                            game_process_suspended = game_proc
                                            log.info(f"GameMonitor: ✓ SUSPENDED game process successfully")
                                        except psutil.AccessDenied as e:
                                            log.error(f"GameMonitor: ✗ ACCESS DENIED - Cannot suspend (need admin rights?)")
                                            log.error(f"GameMonitor: Try running SkinCloner as Administrator")
                                            return
                                        except Exception as e:
                                            log.error(f"GameMonitor: ✗ Failed to suspend: {type(e).__name__}: {e}")
                                            return
                                            
                                    elif ENABLE_GAME_THROTTLE:
                                        try:
                                            game_proc.nice(psutil.IDLE_PRIORITY_CLASS)
                                            nonlocal game_process_throttled
                                            game_process_throttled = game_proc
                                            log.info(f"GameMonitor: ✓ Throttled game to IDLE priority")
                                        except psutil.AccessDenied as e:
                                            log.error(f"GameMonitor: ✗ ACCESS DENIED - Cannot throttle (need admin rights?)")
                                            log.error(f"GameMonitor: Try running SkinCloner as Administrator")
                                            return
                                        except Exception as e:
                                            log.error(f"GameMonitor: ✗ Failed to throttle: {type(e).__name__}: {e}")
                                            return
                                    
                                    log.info(f"GameMonitor: Game delay active - injection can take up to {max_wait}s")
                                    return  # Found and throttled, exit
                                    
                                except psutil.NoSuchProcess:
                                    log.debug(f"GameMonitor: Process {proc.info['pid']} disappeared before we could access it")
                                    continue  # Keep looking
                                except Exception as proc_error:
                                    log.error(f"GameMonitor: ✗ Unexpected error: {type(proc_error).__name__}: {proc_error}")
                                    log.error(f"GameMonitor: Process PID={proc.info['pid']}, Name={proc.info['name']}")
                                    return  # Exit on error
                        
                        time.sleep(0.05)  # Check every 50ms
                    
                    if time.time() - start_wait >= max_wait:
                        log.warning(f"GameMonitor: ✗ Game process NOT FOUND after {max_wait}s - no throttling applied")
                        
                        # DEBUG: Show what processes ARE running
                        league_procs = []
                        for p in psutil.process_iter(['name', 'pid']):
                            if 'league' in p.info['name'].lower():
                                league_procs.append(f"{p.info['name']} (PID={p.info['pid']})")
                        if league_procs:
                            log.warning(f"GameMonitor: League processes found: {', '.join(league_procs)}")
                        else:
                            log.warning("GameMonitor: No League processes found at all!")
                    elif not game_monitor_active:
                        log.info("GameMonitor: Stopped before finding game process")
                        
                except Exception as e:
                    log.error(f"GameMonitor: Error: {e}")
            
            # Start monitor thread
            monitor_thread = threading.Thread(target=monitor_and_throttle_game, daemon=True)
            monitor_thread.start()
            log.info(f"GameMonitor: Background monitor started ({'SUSPENSION' if ENABLE_GAME_SUSPENSION else 'THROTTLE'} mode)")
        
        try:
            # Clean mods and overlay directories, then extract new skin
            clean_start = time.time()
            self._clean_mods_dir()
            self._clean_overlay_dir()
            clean_duration = time.time() - clean_start
            log.debug(f"Injector: Directory cleanup took {clean_duration:.2f}s")
            
            extract_start = time.time()
            mod_folder = self._extract_zip_to_mod(zp)
            extract_duration = time.time() - extract_start
            log.debug(f"Injector: ZIP extraction took {extract_duration:.2f}s")
        
            # Create and run overlay
            result = self._mk_run_overlay([mod_folder.name], timeout, stop_callback)
            
            # Get mkoverlay duration from stored timing data
            mkoverlay_duration = self.last_injection_timing.get('mkoverlay_duration', 0.0) if self.last_injection_timing else 0.0
            
            total_duration = time.time() - injection_start_time
            runoverlay_duration = total_duration - clean_duration - extract_duration - mkoverlay_duration
            
            # Log timing breakdown
            if result == 0:
                log.info(f"Injector: Completed in {total_duration:.2f}s (mkoverlay: {mkoverlay_duration:.2f}s, runoverlay: {runoverlay_duration:.2f}s)")
            else:
                log.warning(f"Injector: Failed - timeout or error after {total_duration:.2f}s (mkoverlay: {mkoverlay_duration:.2f}s)")
            
            return result == 0
            
        finally:
            # Stop game monitor
            game_monitor_active = False
            
            # Restore game process priority/state
            if game_process_suspended:
                try:
                    game_process_suspended.resume()
                    log.info(f"GameMonitor: Resumed game process (PID={game_process_suspended.pid})")
                except Exception as e:
                    log.warning(f"GameMonitor: Failed to resume game process: {e}")
            
            if game_process_throttled:
                try:
                    import psutil
                    game_process_throttled.nice(psutil.NORMAL_PRIORITY_CLASS)
                    log.info(f"GameMonitor: Restored game priority to NORMAL (PID={game_process_throttled.pid})")
                except Exception as e:
                    log.debug(f"GameMonitor: Failed to restore game priority: {e}")
    
    def inject_skin_for_testing(self, skin_name: str) -> bool:
        """Inject a skin for testing - stops overlay immediately after mkoverlay"""
        try:
            log.debug(f"Injector: Starting test injection for: {skin_name}")
            
            # Find the skin ZIP
            zp = self._resolve_zip(skin_name)
            if not zp:
                log.error(f"Injector: Skin '{skin_name}' not found in {self.zips_dir}")
                return False
            
            log.debug(f"Injector: Using skin file: {zp}")
            
            # Clean and extract
            injection_start_time = time.time()
            self._clean_mods_dir()
            clean_duration = time.time() - injection_start_time
            
            extract_start_time = time.time()
            mod_folder = self._extract_zip_to_mod(zp)
            extract_duration = time.time() - extract_start_time
            
            if not mod_folder:
                log.error(f"Injector: Failed to extract skin: {skin_name}")
                return False
            
            # Run mkoverlay only (no runoverlay)
            result = self._mk_overlay_only([mod_folder.name])
            
            # Get mkoverlay duration from stored timing data
            mkoverlay_duration = self.last_injection_timing.get('mkoverlay_duration', 0.0) if self.last_injection_timing else 0.0
            total_duration = time.time() - injection_start_time
            
            if result == 0:
                log.info(f"Injector: Test injection completed in {total_duration:.2f}s (clean: {clean_duration:.2f}s, extract: {extract_duration:.2f}s, mkoverlay: {mkoverlay_duration:.2f}s)")
                return True
            else:
                log.error(f"Injector: Test injection failed with code: {result}")
                return False
                
        except Exception as e:
            log.error(f"Injector: Test injection failed: {e}")
            return False
    
    def _run_overlay_from_path(self, overlay_path: Path) -> bool:
        """Run overlay from an overlay directory"""
        try:
            log.info(f"Injector: Running overlay from: {overlay_path}")
            
            # Check what's in the overlay directory
            overlay_contents = list(overlay_path.iterdir())
            log.debug(f"Injector: Overlay contents: {[f.name for f in overlay_contents]}")
            
            if not overlay_contents:
                log.error(f"Injector: Overlay directory is empty: {overlay_path}")
                return False
            
            # Copy overlay to the main overlay directory
            main_overlay_dir = self.mods_dir.parent / "overlay"
            
            # Clean main overlay directory
            if main_overlay_dir.exists():
                shutil.rmtree(main_overlay_dir, ignore_errors=True)
            main_overlay_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy overlay contents
            log.debug(f"Injector: Copying from {overlay_path} to {main_overlay_dir}")
            for item in overlay_path.iterdir():
                if item.is_file():
                    shutil.copy2(item, main_overlay_dir / item.name)
                    log.debug(f"Injector: Copied file: {item.name}")
                elif item.is_dir():
                    shutil.copytree(item, main_overlay_dir / item.name)
                    log.debug(f"Injector: Copied directory: {item.name}")
            
            # Log what's in the main overlay directory after copying
            overlay_files = list(main_overlay_dir.iterdir())
            log.debug(f"Injector: Main overlay directory contents: {[f.name for f in overlay_files]}")
            
            # Run overlay using runoverlay command
            tools = self._detect_tools()
            exe = tools.get("modtools")
            if not exe or not exe.exists():
                log.error(f"[INJECTOR] Missing mod-tools.exe in {self.tools_dir}")
                return False
            
            # Create configuration file path
            cfg = main_overlay_dir / "cslol-config.json"
            gpath = str(self.game_dir)
            
            cmd = [
                str(exe), "runoverlay", str(main_overlay_dir), str(cfg),
                f"--game:{gpath}", "--opts:configless"
            ]
            
            log.info(f"Injector: Running overlay: {' '.join(cmd)}")
            
            try:
                # Hide console window on Windows
                import sys
                creationflags = 0
                if sys.platform == "win32":
                    import subprocess
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags)
                self.current_overlay_process = proc
                
                # For pre-built overlays, we don't need to monitor the process long-term
                # Just start it and let it run in the background
                log.info("Injector: Pre-built overlay process started successfully")
                return True
                
            except Exception as e:
                log.error(f"Injector: Error running overlay process: {e}")
                return False
                
        except Exception as e:
            log.error(f"Injector: Error running pre-built overlay: {e}")
            return False
    
    def clean_system(self) -> bool:
        """Clean the injection system"""
        try:
            if self.mods_dir.exists():
                shutil.rmtree(self.mods_dir, ignore_errors=True)
            overlay_dir = self.mods_dir.parent / "overlay"
            if overlay_dir.exists():
                shutil.rmtree(overlay_dir, ignore_errors=True)
            log.debug("Injector: System cleaned successfully")
            return True
        except Exception as e:
            log.error(f"Injector: Failed to clean system: {e}")
            return False
    
    def stop_overlay_process(self):
        """Stop the current overlay process"""
        if self.current_overlay_process and self.current_overlay_process.poll() is None:
            try:
                log.info("Injector: Stopping current overlay process")
                self.current_overlay_process.terminate()
                try:
                    self.current_overlay_process.wait(timeout=PROCESS_TERMINATE_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    self.current_overlay_process.kill()
                    self.current_overlay_process.wait()
                self.current_overlay_process = None
                log.info("Injector: Overlay process stopped successfully")
            except Exception as e:
                log.warning(f"Injector: Failed to stop overlay process: {e}")
        else:
            log.debug("Injector: No active overlay process to stop")
    
    def kill_all_runoverlay_processes(self):
        """Kill all runoverlay processes (for ChampSelect cleanup)"""
        import psutil
        killed_count = 0
        
        try:
            # Find all processes with "runoverlay" in command line
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and any('runoverlay' in arg for arg in cmdline):
                        log.info(f"Injector: Killing runoverlay process PID {proc.info['pid']}")
                        proc.kill()
                        killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process might have already ended or we don't have access
                    pass
            
            if killed_count > 0:
                log.info(f"Injector: Killed {killed_count} runoverlay process(es)")
            else:
                log.debug("Injector: No runoverlay processes found to kill")
                
        except Exception as e:
            log.warning(f"Injector: Failed to kill runoverlay processes: {e}")
        
        # Also stop our tracked process if it exists
        self.stop_overlay_process()