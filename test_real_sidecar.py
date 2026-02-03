import subprocess
import asyncio
import websockets
import json
import sys
import os
import signal
from pathlib import Path

# Configuration
IS_WINDOWS = sys.platform == "win32"
BIN_NAME = "sidecar.exe" if IS_WINDOWS else "sidecar"
WS_URI = "ws://127.0.0.1:13337"

# Target Room ID and Response Payload
TARGET_ROOM_ID = "5f8c9d8a-3ec6-492f-8609-d3799aa128db"
BRAUM_PAYLOAD = {
    "action": "UpdateSkin",
    "payload": {
        "champion_id": 201,
        "skin_id": 201042,
        "skin_name": "Braum Bán Kebab",
        "is_custom": False
    }
}

# Search paths for sidecar binary
SEARCH_PATHS = [
    Path(f"sidecar/target/release/{BIN_NAME}"),
    Path(f"sidecar/target/debug/{BIN_NAME}"),
    Path(f"tools/{BIN_NAME}"),
    Path(BIN_NAME)
]

def print_separator():
    print("=" * 60)

async def automated_loop(ws):
    """Automated loop: Join Room -> Wait for RemoteSkinUpdate -> Reply"""
    
    print_separator()
    print(" ROSE AUTOMATED TEST BOT ")
    print(f" Target Room: {TARGET_ROOM_ID}")
    print_separator()

    # 1. Join Room
    print(f"[AUTO] Joining Room {TARGET_ROOM_ID}...")
    join_msg = {
        "action": "JoinRoom",
        "payload": {
            "room_id": TARGET_ROOM_ID
        }
    }
    await ws.send(json.dumps(join_msg))
    print("[TX] JoinRoom sent.")

    print("\n[AUTO] Waiting for incoming skin updates from peer...")
    print("(Go to Rose App and inject a skin now)")
    # 2. Listen loop
    try:
        async for message in ws:
            try:
                data = json.loads(message)
                event_type = data.get("event")
                    
                    # Print received message
                    # print(f"\n[RX] {json.dumps(data, indent=2)}") 
                    # Simplify log to avoid spamming screen
                if event_type:
                    print(f"[RX] Event: {event_type}")

                    # Logic: If we receive a RemoteSkinUpdate, it means the other user injected.
                    # We should reply with our Braum skin.
                if event_type == "RemoteSkinUpdate":
                    payload = data.get("data", {})
                    peer_name = payload.get("skin_name", "Unknown")
                    print(f"\n>>> DETECTED BROADCAST: {peer_name} (ID: {payload.get('skin_id')})")
                        
                    print("[AUTO] Replying with 'Braum Bán Kebab' in 1 second...")
                    await asyncio.sleep(1)
                        
                    await ws.send(json.dumps(BRAUM_PAYLOAD))
                    print("[TX] Auto-reply sent: Braum Bán Kebab")
                    
                elif event_type == "PeerJoined":
                    print(f"[INFO] A peer joined the room: {data.get('data', {}).get('peer_id')}")

            except json.JSONDecodeError:
                print(f"[RX RAW] {message}")
                    
    except websockets.exceptions.ConnectionClosed:
        print("\n[Listener] WebSocket connection closed.")
    except Exception as e:
        print(f"\n[Listener] Error: {e}")

async def main():
    # 1. Check if sidecar exists
    sidecar_path = next((p for p in SEARCH_PATHS if p.exists()), None)
    
    if not sidecar_path:
        print(f"[Error] Could not find sidecar binary ({BIN_NAME}) in common locations.")
        print("Checked paths:")
        for p in SEARCH_PATHS:
            print(f" - {p}")
        return

    # Ensure executable permissions on Linux/macOS
    if not IS_WINDOWS:
        try:
            if not os.access(sidecar_path, os.X_OK):
                print(f"Adding execute permission to {sidecar_path}...")
                os.chmod(sidecar_path, 0o755)
        except Exception as e:
            print(f"[Warning] Failed to set execute permission: {e}")

    # 2. Start Sidecar process
    print(f"Launching {sidecar_path}...")
    try:
        process = subprocess.Popen(
            [str(sidecar_path)],
            cwd=os.getcwd()
        )
    except Exception as e:
        print(f"[Error] Failed to launch sidecar: {e}")
        return

    # Allow some time for startup
    await asyncio.sleep(1)

    # 3. Connect loop
    connected = False
    retries = 5
    ws = None
    
    while retries > 0:
        try:
            ws = await websockets.connect(WS_URI)
            connected = True
            break
        except Exception as e:
            print(f"Connection attempt failed ({retries} left): {e}")
            await asyncio.sleep(1)
            retries -= 1

    if not connected:
        print("[Error] Could not connect to Sidecar.")
        process.terminate()
        return

    # 4. Run Main Logic
    try:
        await automated_loop(ws)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        print("\nClosing connection...")
        try:
            await ws.close()
        except: pass
        
        print("Terminating Sidecar...")
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        
        print("Done.")

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
