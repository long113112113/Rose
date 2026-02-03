import subprocess
import asyncio
import websockets
import json
import sys
import os
import signal
from pathlib import Path
import threading

# Configuration
SIDECAR_PATH = Path("sidecar/target/release/sidecar.exe")
WS_URI = "ws://127.0.0.1:13337"

def print_separator():
    print("=" * 60)

async def listener(ws):
    """Background task to listen for incoming messages from Sidecar."""
    try:
        async for message in ws:
            try:
                data = json.loads(message)
                print(f"\n[RX] {json.dumps(data, indent=2)}")
                print("> ", end="", flush=True)  # Restore prompt
            except json.JSONDecodeError:
                print(f"\n[RX RAW] {message}")
                print("> ", end="", flush=True)
    except websockets.exceptions.ConnectionClosed:
        print("\n[Listener] WebSocket connection closed.")
    except Exception as e:
        print(f"\n[Listener] Error: {e}")

async def input_loop(ws):
    """Main interactive loop."""
    loop = asyncio.get_event_loop()
    
    print_separator()
    print(" ROSE SIDECAR TEST CLIENT ")
    print(f" Connected to: {WS_URI}")
    print_separator()
    print("COMMANDS:")
    print(" 1. Join Room (PartyID)")
    print(" 2. Send Skin Update")
    print(" 3. Send raw JSON")
    print(" q. Quit")
    print_separator()

    while True:
        # Run input in executor to avoid blocking the event loop
        print("> ", end="", flush=True)
        cmd = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = cmd.strip()

        if not cmd:
            continue

        if cmd == "q":
            print("Exiting...")
            break

        payload = None

        if cmd == "1":
            print("Enter Party ID (Room ID): ", end="", flush=True)
            party_id = await loop.run_in_executor(None, sys.stdin.readline)
            party_id = party_id.strip()
            if party_id:
                payload = {
                    "action": "JoinRoom",
                    "payload": {
                        "room_id": party_id
                    }
                }

        elif cmd == "2":
            try:
                print("Press Enter to use default (Braum Bán Kebab) or type specific ID.")
                print("Enter Champion ID [201]: ", end="", flush=True)
                cid_str = await loop.run_in_executor(None, sys.stdin.readline)
                cid = int(cid_str.strip()) if cid_str.strip() else 201
                
                print("Enter Skin ID [201042]: ", end="", flush=True)
                sid_str = await loop.run_in_executor(None, sys.stdin.readline)
                sid = int(sid_str.strip()) if sid_str.strip() else 201042
                
                print("Enter Skin Name [Braum Bán Kebab]: ", end="", flush=True)
                sname = await loop.run_in_executor(None, sys.stdin.readline)
                sname = sname.strip() or "Braum Bán Kebab"
                
                payload = {
                    "action": "UpdateSkin",
                    "payload": {
                        "champion_id": cid,
                        "skin_id": sid,
                        "skin_name": sname,
                        "is_custom": False
                    }
                }
            except ValueError:
                print("[Error] Invalid input. IDs must be integers.")

        elif cmd == "3":
            print("Enter Raw JSON: ", end="", flush=True)
            raw = await loop.run_in_executor(None, sys.stdin.readline)
            try:
                payload = json.loads(raw.strip())
            except json.JSONDecodeError:
                print("[Error] Invalid JSON.")

        else:
            print("[Error] Unknown command.")

        if payload:
            try:
                msg_str = json.dumps(payload)
                await ws.send(msg_str)
                print(f"[TX] {msg_str}")
            except Exception as e:
                print(f"[TX Error] {e}")

async def main():
    # 1. Check if sidecar exists
    if not SIDECAR_PATH.exists():
        # Fallback to looking in current directory or tools
        if Path("tools/sidecar.exe").exists():
           sidecar_path = Path("tools/sidecar.exe")
        elif Path("sidecar.exe").exists():
           sidecar_path = Path("sidecar.exe")
        else:
           print(f"[Error] Could not find sidecar.exe at {SIDECAR_PATH} or common locations.")
           return
    else:
        sidecar_path = SIDECAR_PATH

    # 2. Start Sidecar process
    print(f"Launching {sidecar_path}...")
    try:
        # Launch with CREATE_NO_WINDOW if on Windows to keep it cleaner, 
        # but let's keep it visible or piped for debug.
        # Using subprocess.PIPE for stdout/stderr to suppress noise unless we handle it,
        # but the user might want to see sidecar logs.
        # Let's let it inherit stdout/stderr for now so user sees Rust logs too.
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

    # 4. Run Main Loop
    try:
        # Start listener task
        listener_task = asyncio.create_task(listener(ws))
        
        # Run input loop
        await input_loop(ws)
        
        # Cleanup
        listener_task.cancel()
    except Exception as e:
        print(f"[Error] Main loop crashed: {e}")
    finally:
        print("Closing connection...")
        await ws.close()
        
        print("Terminating Sidecar...")
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        
        print("Done.")

if __name__ == "__main__":
    try:
        # On Windows, SelectorEventLoop is needed for subprocess
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
