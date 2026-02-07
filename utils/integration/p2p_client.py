import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Callable, Dict, Any

import websockets

from utils.core.paths import get_app_dir

log = logging.getLogger(__name__)

class P2PClient:
    """
    Client for communicating with the Rose Rust Sidecar (P2P Node).
    """

    PORT = 13337
    URI = f"ws://127.0.0.1:{PORT}"

    def __init__(self):
        log.info("[P2P] Initializing P2P Client (Updated logic)")
        self._websocket = None
        self._process: Optional[subprocess.Popen] = None
        self._connected = False
        self._callbacks: Dict[str, Callable] = {}
        self._running = False
        self._running = False
        self._reconnect_task = None
        self._job_handle = None
        self._node_id_future: Optional[asyncio.Future] = None
        self._my_node_id: Optional[str] = None

    async def start(self, manage_process=True):
        """Start the sidecar process and connect to it."""
        if manage_process:
            self._start_sidecar_process()
        
        self.loop = asyncio.get_running_loop()
        self._running = True
        self._reconnect_task = asyncio.create_task(self._connect_loop())

    def _start_sidecar_process(self):
        """Launch the Rust sidecar executable."""
        base_path = get_app_dir()
        
        # Check multiple possible locations
        possible_paths = [
            # Dev path: sidecar/target/release/sidecar.exe
            base_path / "sidecar" / "target" / "release" / "sidecar.exe",
            # Dev path (debug build)
            base_path / "sidecar" / "target" / "debug" / "sidecar.exe",
            # Production/PyInstaller onedir: _internal/injection/tools/
            base_path / "_internal" / "injection" / "tools" / "sidecar.exe",
            # Production/PyInstaller (legacy)
            base_path / "injection" / "tools" / "sidecar.exe"
        ]
        
        sidecar_path = None
        for path in possible_paths:
            if path.exists():
                sidecar_path = path
                break
        
        if not sidecar_path:
            searched_paths = "\n  - ".join(str(p) for p in possible_paths)
            error_msg = (
                f"[P2P] CRITICAL: sidecar.exe not found!\n"
                f"  Base path: {base_path}\n"
                f"  Searched locations:\n  - {searched_paths}\n"
                f"  P2P features will be DISABLED."
            )
            log.error(error_msg)
            return

        try:
            log.info(f"Launching sidecar: {sidecar_path}")
            
            # Hide console window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Determine logs directory
            from utils.core.paths import get_user_data_dir
            logs_dir = get_user_data_dir() / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            cmd = [str(sidecar_path), "--log-dir", str(logs_dir)]
            
            self._process = subprocess.Popen(
                cmd,
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,  # Text mode for easier reading
                bufsize=1   # Line buffered
            )
            
            # Start threads to read output
            threading.Thread(target=self._log_sidecar_output, args=(self._process.stdout, "STDOUT"), daemon=True).start()
            threading.Thread(target=self._log_sidecar_output, args=(self._process.stderr, "STDERR"), daemon=True).start()
            
            if os.name == 'nt':
                self._assign_job_object()
        except Exception as e:
            log.error(f"Failed to start sidecar: {e}")

    def _log_sidecar_output(self, pipe, name):
        """Read and log sidecar output"""
        try:
            for line in iter(pipe.readline, ''):
                if line:
                    log.info(f"[Sidecar] {line.strip()}")
        except Exception:
            pass

    async def _connect_loop(self):
        """Maintain WebSocket connection."""
        while self._running:
            try:
                # Disable ping from client side, let server handle it or implied by traffic
                async with websockets.connect(self.URI, ping_interval=None) as websocket:
                    self._websocket = websocket
                    self._connected = True
                    log.info("Connected to P2P Sidecar")
                    
                    await self._message_handler()
            except ConnectionRefusedError:
                # Sidecar might be starting up
                await asyncio.sleep(1)
            except Exception as e:
                log.error(f"P2P Connection error: {e}")
                self._connected = False
                await asyncio.sleep(5)
            finally:
                self._connected = False
                self._websocket = None

    async def _message_handler(self):
        """Handle incoming messages from sidecar."""
        if not self._websocket:
            return

        async for message in self._websocket:
            try:
                data = json.loads(message)
                event_type = data.get("event")
                payload = data.get("data")
                
                log.debug(f"P2P Event: {event_type}")
                log.debug(f"P2P Data: {json.dumps(payload, ensure_ascii=False)}")

                # Handle NodeId response
                if event_type == "NodeId" and self._node_id_future:
                    self._my_node_id = payload
                    self._node_id_future.set_result(payload)
                    self._node_id_future = None
                elif event_type in self._callbacks:
                    await self._callbacks[event_type](payload)
                    
            except json.JSONDecodeError:
                log.warn(f"Received invalid JSON from sidecar: {message}")
            except Exception as e:
                log.error(f"Error handling P2P message: {e}")

    async def get_node_id(self, timeout: float = 5.0) -> Optional[str]:
        """Get the sidecar's node ID.
        
        Args:
            timeout: Max seconds to wait for response
            
        Returns:
            Node ID string or None if failed
        """
        if self._my_node_id:
            return self._my_node_id
            
        if not self._connected:
            log.warning("Cannot get node ID, sidecar not connected")
            return None
        
        self._node_id_future = asyncio.get_running_loop().create_future()
        await self.send_action("GetNodeId", None)
        
        try:
            result = await asyncio.wait_for(self._node_id_future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            log.warning("Timeout waiting for NodeId from sidecar")
            self._node_id_future = None
            return None

    def get_cached_node_id(self) -> Optional[str]:
        """Get cached node ID without async call."""
        return self._my_node_id

    async def send_action(self, action: str, payload: Any = None):
        """Send a command to the sidecar."""
        if not self._websocket or not self._connected:
            log.warn("Cannot send action, sidecar not connected")
            return

        msg = {
            "action": action,
            "payload": payload
        }
        try:
            log.debug(f"P2P Send Action: {action}")
            log.debug(f"P2P Send Payload: {json.dumps(payload, ensure_ascii=False)}")
            await self._websocket.send(json.dumps(msg))
        except Exception as e:
            log.error(f"Failed to send action {action}: {e}")
            
    def send_action_sync(self, action: str, payload: Any = None):
        """Thread-safe synchronous wrapper for send_action"""
        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_action(action, payload), self.loop)
        else:
            log.warning("Cannot send_action_sync: P2P loop not running")

    async def join_via_nodemaster(self, ticket: str, nodemaster_url: str = None):
        """Join a P2P room via NodeMaster server for peer discovery.
        
        This is the preferred method for joining P2P rooms. The sidecar will:
        1. Connect to NodeMaster server
        2. Register with the ticket to get peer list
        3. Use the peer list to bootstrap iroh-gossip connections
        
        Args:
            ticket: The room ticket (topic hash, 64 hex chars)
            nodemaster_url: Optional custom NodeMaster URL (default: ws://127.0.0.1:31337)
        """
        payload = {
            "ticket": ticket,
            "nodemaster_url": nodemaster_url
        }
        await self.send_action("JoinViaNodeMaster", payload)
        log.info(f"[P2P] Sent JoinViaNodeMaster for ticket: {ticket[:16]}...")

    def join_via_nodemaster_sync(self, ticket: str, nodemaster_url: str = None):
        """Thread-safe synchronous wrapper for join_via_nodemaster"""
        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.join_via_nodemaster(ticket, nodemaster_url), 
                self.loop
            )
        else:
            log.warning("Cannot join_via_nodemaster_sync: P2P loop not running")

    async def leave_room(self):
        """Leave the current P2P room.
        
        This will:
        1. Notify NodeMaster server (if connected)
        2. Clean up gossip subscriptions
        3. Trigger NeighborDown events for connected peers
        """
        await self.send_action("LeaveRoom", None)
        log.info("[P2P] Sent LeaveRoom command")

    def leave_room_sync(self):
        """Thread-safe synchronous wrapper for leave_room"""
        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.leave_room(), self.loop)
        else:
            log.warning("Cannot leave_room_sync: P2P loop not running")

    def on(self, event: str, callback: Callable):
        """Register a callback for a specific event type."""
        self._callbacks[event] = callback

    def _assign_job_object(self):
        """Assign the sidecar process to a Windows Job Object to ensure cleanup."""
        try:
            import ctypes
            
            # Constants
            JobObjectExtendedLimitInformation = 9
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
            
            # Structures (Partial definition sufficient for our needs, but we need correct size)
            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ('PerProcessUserTimeLimit', ctypes.c_int64),
                    ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', ctypes.c_ulong),
                    ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', ctypes.c_ulong),
                    ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', ctypes.c_ulong),
                    ('SchedulingClass', ctypes.c_ulong),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('ReadOperationCount', ctypes.c_ulonglong),
                    ('WriteOperationCount', ctypes.c_ulonglong),
                    ('OtherOperationCount', ctypes.c_ulonglong),
                    ('ReadTransferCount', ctypes.c_ulonglong),
                    ('WriteTransferCount', ctypes.c_ulonglong),
                    ('OtherTransferCount', ctypes.c_ulonglong),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ('IoInfo', IO_COUNTERS),
                    ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t),
                ]

            # Create Job Object
            self._job_handle = ctypes.windll.kernel32.CreateJobObjectW(None, None)
            
            # Configure Job Object
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            
            ctypes.windll.kernel32.SetInformationJobObject(
                self._job_handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
            )
            
            # Assign Process to Job Object
            ctypes.windll.kernel32.AssignProcessToJobObject(
                self._job_handle, 
                ctypes.c_void_p(self._process._handle)
            )
            
        except Exception as e:
            log.warning(f"Failed to configure Job Object: {e}")

    def stop(self):
        """Stop the client and kill the sidecar."""
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
        
        if self._process:
            self._process.terminate()
            self._process = None

# Singleton instance
p2p_client = P2PClient()
