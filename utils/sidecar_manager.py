
import sys
import subprocess
import atexit
import time
from pathlib import Path
from utils.core.logging import get_logger

log = get_logger()
_sidecar_process = None

def get_sidecar_path():
    """Lấy đường dẫn tuyệt đối của sidecar.exe"""
    if getattr(sys, 'frozen', False):
        # Khi chạy file EXE đã đóng gói (Onedir mode)
        # sys.executable là đường dẫn đến Rose.exe
        # Trong bản build, ta sẽ để sidecar.exe nằm cùng thư mục với các tool khác (injection/tools)
        # hoặc nằm ở root nếu muốn. Theo Rose.spec, ta sẽ map nó vào injection/tools
        base_dir = Path(sys.executable).parent
        return base_dir / "injection" / "tools" / "sidecar.exe"
    else:
        # Khi chạy source code (Dev mode)
        # User yêu cầu file exe nằm trong thư mục tools (d:\Rose\tools)
        # File này nằm ở utils/sidecar_manager.py -> cha -> cha -> tools
        base_dir = Path(__file__).resolve().parent.parent
        return base_dir / "tools" / "sidecar.exe"

def start_sidecar():
    """Khởi chạy sidecar process"""
    global _sidecar_process
    
    # Nếu đã chạy rồi thì thôi
    if _sidecar_process is not None:
        if _sidecar_process.poll() is None:
            return
    
    exe_path = get_sidecar_path()
    
    if not exe_path.exists():
        log.error(f"Sidecar executable not found at: {exe_path}")
        return

    try:
        # CREATE_NO_WINDOW = 0x08000000 để ẩn cửa sổ console của sidecar
        # creationflags = 0x08000000 if sys.platform == "win32" else 0
        creationflags = 0 # DISPLAY WINDOW FOR DEBUGGING
        
        log.info(f"Starting Sidecar: {exe_path}")
        _sidecar_process = subprocess.Popen(
            [str(exe_path)],
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        log.info(f"Sidecar started with PID: {_sidecar_process.pid}")
        
        # Đảm bảo tắt sidecar khi Rose tắt
        atexit.register(stop_sidecar)
        
    except Exception as e:
        log.error(f"Failed to start sidecar: {e}")

def stop_sidecar():
    """Tắt sidecar process"""
    global _sidecar_process
    if _sidecar_process:
        log.info("Stopping Sidecar...")
        _sidecar_process.terminate()
        try:
            _sidecar_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _sidecar_process.kill()
        _sidecar_process = None
