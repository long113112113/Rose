import subprocess
import asyncio
import websockets
import json
import sys
import os
import argparse
import hashlib
from pathlib import Path

# Configuration
IS_WINDOWS = sys.platform == "win32"
BIN_NAME = "sidecar.exe" if IS_WINDOWS else "sidecar"
WS_URI = "ws://127.0.0.1:13337"

# Hardcoded test ticket (64 hex chars) for real testing
# All clients using this ticket will join the same P2P room
TEST_TICKET = "dd56d3021d6cfb0dc8b6aa8b2f84352451cd2dbb6d77e5ff30168c11de9d5944"

# Response Payload for auto-reply
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

def hash_to_ticket(value: str) -> str:
    """Hash any string (partyId, room name, etc.) to 64-char hex ticket"""
    return hashlib.sha256(value.encode()).hexdigest()

def print_separator():
    print("=" * 60)

def print_header(mode: str, ticket: str = None):
    print_separator()
    print(" ROSE P2P TEST CLIENT ")
    print(f" Mode: {mode}")
    if ticket:
        print(f" Ticket: {ticket}")
    print_separator()

async def create_room_flow(ws):
    """Create a new room and wait for peers to join"""
    
    print_header("CREATE ROOM")
    
    # 1. Create Ticket
    print("[ACTION] Creating new room...")
    create_msg = {"action": "CreateTicket", "payload": None}
    await ws.send(json.dumps(create_msg))
    
    # 2. Wait for TicketCreated response
    try:
        response = await asyncio.wait_for(ws.recv(), timeout=10.0)
        data = json.loads(response)
        event_type = data.get("event")
        
        if event_type == "TicketCreated":
            ticket = data.get("data")
            print(f"\n[SUCCESS] Room created!")
            print(f"[TICKET] {ticket}")
            print(f"\n>>> Share this ticket with your teammates! <<<\n")
            return ticket
        elif event_type == "Error":
            message = data.get("data", {}).get("message", "Unknown error")
            print(f"[ERROR] Failed to create room: {message}")
            return None
        else:
            print(f"[WARN] Unexpected response: {event_type}")
            print(f"[DATA] {data}")
            return None
            
    except asyncio.TimeoutError:
        print("[ERROR] Timeout waiting for room creation!")
        return None

async def join_room_flow(ws, ticket: str):
    """Join an existing room with a ticket"""
    
    print_header("JOIN ROOM", ticket)
    
    # 1. Join Ticket
    print(f"[ACTION] Joining room...")
    join_msg = {"action": "JoinTicket", "payload": ticket}
    await ws.send(json.dumps(join_msg))
    
    # 2. Wait for confirmation
    try:
        response = await asyncio.wait_for(ws.recv(), timeout=10.0)
        data = json.loads(response)
        event_type = data.get("event")
        
        if event_type == "JoinedRoom":
            joined_ticket = data.get("data", {}).get("ticket", "")
            print(f"[SUCCESS] Joined room: {joined_ticket}")
            return True
        elif event_type == "InvalidTicket":
            reason = data.get("data", {}).get("reason", "Unknown")
            print(f"[ERROR] Invalid ticket!")
            print(f"[REASON] {reason}")
            return False
        elif event_type == "Error":
            message = data.get("data", {}).get("message", "Unknown error")
            print(f"[ERROR] {message}")
            return False
        else:
            print(f"[WARN] Unexpected response: {event_type}")
            # Continue anyway
            return True
            
    except asyncio.TimeoutError:
        print("[ERROR] Timeout waiting for join confirmation!")
        return False

async def listen_loop(ws, auto_reply: bool = True):
    """Main event loop - listen for P2P events"""
    
    print("\n[LISTENING] Waiting for P2P events...")
    print("  - PeerJoined: When a teammate joins")
    print("  - RemoteSkinUpdate: When someone injects a skin")
    print("  - SyncConfirmed: When your skin was received")
    print("\nPress Ctrl+C to exit.\n")
    
    try:
        async for message in ws:
            try:
                data = json.loads(message)
                event_type = data.get("event")
                payload = data.get("data", {})
                
                if event_type == "PeerJoined":
                    peer_id = payload.get("peer_id", "Unknown")[:16]
                    print(f"[PEER+] Teammate joined: {peer_id}...")
                    
                elif event_type == "PeerLeft":
                    peer_id = payload.get("peer_id", "Unknown")[:16]
                    print(f"[PEER-] Teammate left: {peer_id}...")
                    
                elif event_type == "RemoteSkinUpdate":
                    skin_name = payload.get("skin_name", "Unknown")
                    skin_id = payload.get("skin_id")
                    champion_id = payload.get("champion_id")
                    peer_id = payload.get("peer_id", "")[:16]
                    
                    print(f"\n>>> SKIN BROADCAST FROM {peer_id}...")
                    print(f"    Champion: {champion_id}")
                    print(f"    Skin: {skin_name} (ID: {skin_id})")
                    
                    if auto_reply:
                        print("[AUTO] Sending reply skin in 1 second...")
                        await asyncio.sleep(1)
                        await ws.send(json.dumps(BRAUM_PAYLOAD))
                        print("[TX] Sent: Braum Bán Kebab")
                        
                elif event_type == "SyncConfirmed":
                    peer_id = payload.get("peer_id", "Unknown")[:16]
                    print(f"[ACK] {peer_id}... confirmed receiving your skin")
                    
                elif event_type == "Log":
                    level = payload.get("level", "INFO")
                    message = payload.get("message", "")
                    print(f"[{level}] {message}")
                    
                else:
                    print(f"[EVENT] {event_type}: {json.dumps(payload)}")
                    
            except json.JSONDecodeError:
                print(f"[RAW] {message}")
                
    except websockets.exceptions.ConnectionClosed:
        print("\n[DISCONNECTED] WebSocket connection closed.")
    except Exception as e:
        print(f"\n[ERROR] {e}")

async def send_test_skin(ws):
    """Send a test skin broadcast"""
    print("\n[ACTION] Broadcasting test skin...")
    await ws.send(json.dumps(BRAUM_PAYLOAD))
    print("[TX] Sent: Braum Bán Kebab")

async def main():
    parser = argparse.ArgumentParser(description="Rose P2P Sidecar Test Client")
    parser.add_argument("--join", "-j", type=str, help="Join room (hex ticket or any string to hash)")
    parser.add_argument("--create", "-c", action="store_true", help="Create new room")
    parser.add_argument("--room", "-r", type=str, help="Join room by name (will be hashed)")
    parser.add_argument("--test", "-t", action="store_true", help="Join the hardcoded TEST_TICKET")
    parser.add_argument("--no-auto-reply", action="store_true", help="Disable auto-reply to skin updates")
    parser.add_argument("--no-sidecar", action="store_true", help="Don't start sidecar (assume already running)")
    args = parser.parse_args()
    
    # Default to test mode if no args
    if not args.join and not args.create and not args.room and not args.test:
        print("No mode specified. Using --test by default.")
        print("\nOptions:")
        print("  python test_real_sidecar.py --test      # Join hardcoded test room")
        print("  python test_real_sidecar.py --create    # Create random room")
        print("  python test_real_sidecar.py --room Name # Join by room name")
        args.test = True

    
    process = None
    
    # 1. Find and start sidecar
    if not args.no_sidecar:
        sidecar_path = next((p for p in SEARCH_PATHS if p.exists()), None)
        
        if not sidecar_path:
            print(f"[ERROR] Could not find sidecar binary ({BIN_NAME})")
            print("Checked paths:")
            for p in SEARCH_PATHS:
                print(f"  - {p}")
            return
        
        print(f"[LAUNCH] Starting {sidecar_path}...")
        try:
            process = subprocess.Popen(
                [str(sidecar_path)],
                cwd=os.getcwd()
            )
        except Exception as e:
            print(f"[ERROR] Failed to launch sidecar: {e}")
            return
        
        # Wait for sidecar to start and connect to relay
        print("[WAIT] Waiting for sidecar to connect to relay network...")
        await asyncio.sleep(3)  # Give time for relay connection
    
    # 2. Connect to sidecar WebSocket
    ws = None
    for attempt in range(5):
        try:
            ws = await websockets.connect(WS_URI, ping_interval=None)
            print(f"[CONNECTED] WebSocket connected to {WS_URI}")
            break
        except Exception as e:
            print(f"[RETRY] Connection attempt {attempt+1}/5 failed: {e}")
            await asyncio.sleep(1)
    
    if not ws:
        print("[ERROR] Could not connect to sidecar WebSocket")
        if process:
            process.terminate()
        return
    
    try:
        # 3. Create or Join room
        if args.create:
            ticket = await create_room_flow(ws)
            if not ticket:
                return
        else:
            # Determine ticket to join
            if args.test:
                ticket = TEST_TICKET
                print(f"[INFO] Using hardcoded TEST_TICKET: {ticket}")
            elif args.room:
                # Hash room name to ticket
                ticket = hash_to_ticket(args.room)
                print(f"[INFO] Room name '{args.room}' -> ticket: {ticket}")
            elif args.join and len(args.join) == 64 and all(c in '0123456789abcdefABCDEF' for c in args.join):
                # Already a valid hex ticket
                ticket = args.join.lower()
            else:
                # Hash the input to create a ticket
                ticket = hash_to_ticket(args.join) if args.join else TEST_TICKET
                print(f"[INFO] Input '{args.join}' -> ticket: {ticket}")
            
            success = await join_room_flow(ws, ticket)
            if not success:
                return
        
        # 4. Main listen loop
        await listen_loop(ws, auto_reply=not args.no_auto_reply)
        
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print("\n[EXIT] Shutting down...")
    finally:
        print("[CLEANUP] Closing connections...")
        try:
            await ws.close()
        except:
            pass
        
        if process:
            print("[CLEANUP] Terminating sidecar...")
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        
        print("[DONE] Goodbye!")

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
