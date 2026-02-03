import subprocess
import asyncio
import websockets
import json
import sys
import os
from pathlib import Path

# Configuration
IS_WINDOWS = sys.platform == "win32"
BIN_NAME = "sidecar.exe" if IS_WINDOWS else "sidecar"
WS_URI = "ws://127.0.0.1:13337"

# =====================================================================
# HARDCODED TICKET - Tất cả instance đều dùng chung ticket này
# =====================================================================
HARDCODED_TICKET = "dd56d3021d6cfb0dc8b6aa8b2f84352451cd2dbb6d77e5ff30168c11de9d5944"

# =====================================================================
# DEMO SKIN PAYLOADS - Các skin để test
# =====================================================================
DEMO_SKINS = [
    {
        "action": "UpdateSkin",
        "payload": {
            "champion_id": 201,
            "skin_id": 201042,
            "skin_name": "Braum Bán Kebab",
            "is_custom": False
        }
    },
    {
        "action": "UpdateSkin",
        "payload": {
            "champion_id": 103,
            "skin_id": 103015,
            "skin_name": "Ahri Spirit Blossom",
            "is_custom": False
        }
    },
    {
        "action": "UpdateSkin",
        "payload": {
            "champion_id": 157,
            "skin_id": 157011,
            "skin_name": "Yasuo Nightbringer",
            "is_custom": False
        }
    },
]

# Search paths for sidecar binary
SEARCH_PATHS = [
    Path(f"sidecar/target/release/{BIN_NAME}"),
    Path(f"sidecar/target/debug/{BIN_NAME}"),
    Path(f"tools/{BIN_NAME}"),
    Path(BIN_NAME)
]


def print_separator():
    print("=" * 70)


def print_header(mode: str, ticket: str = None):
    print_separator()
    print("          🌹 ROSE P2P SIDECAR TEST 🌹")
    print(f"          Mode: {mode.upper()}")
    if ticket:
        print(f"          Ticket: {ticket[:32]}...")
    print_separator()


def print_menu():
    print_separator()
    print("          🌹 ROSE P2P SIDECAR TEST MENU 🌹")
    print_separator()
    print("\n  Chọn mode chạy:\n")
    print("    [1] HOST     - Tạo room và broadcast skin liên tục")
    print("    [2] DEFAULT  - Join room và lắng nghe skin từ Host")
    print("    [0] EXIT     - Thoát\n")
    print_separator()


async def create_room_flow(ws):
    """Create a new room and wait for peers to join"""
    print("\n[ACTION] Đang tạo room mới...")
    create_msg = {"action": "CreateTicket", "payload": None}
    await ws.send(json.dumps(create_msg))
    
    try:
        response = await asyncio.wait_for(ws.recv(), timeout=10.0)
        data = json.loads(response)
        event_type = data.get("event")
        
        if event_type == "TicketCreated":
            ticket = data.get("data")
            print(f"\n✅ [SUCCESS] Room đã tạo!")
            print(f"   Ticket: {ticket}")
            return ticket
        elif event_type == "Error":
            message = data.get("data", {}).get("message", "Unknown error")
            print(f"❌ [ERROR] Không thể tạo room: {message}")
            return None
        else:
            print(f"⚠️ [WARN] Unexpected response: {event_type}")
            return None
            
    except asyncio.TimeoutError:
        print("❌ [ERROR] Timeout khi chờ tạo room!")
        return None


async def join_room_flow(ws, ticket: str):
    """Join an existing room with a ticket"""
    print(f"\n[ACTION] Đang join room...")
    print(f"         Ticket: {ticket}")
    
    join_msg = {"action": "JoinTicket", "payload": ticket}
    await ws.send(json.dumps(join_msg))
    
    try:
        response = await asyncio.wait_for(ws.recv(), timeout=10.0)
        data = json.loads(response)
        event_type = data.get("event")
        
        if event_type == "JoinedRoom":
            joined_ticket = data.get("data", {}).get("ticket", "")
            print(f"\n✅ [SUCCESS] Đã join room: {joined_ticket[:32]}...")
            return True
        elif event_type == "InvalidTicket":
            reason = data.get("data", {}).get("reason", "Unknown")
            print(f"❌ [ERROR] Ticket không hợp lệ: {reason}")
            return False
        elif event_type == "Error":
            message = data.get("data", {}).get("message", "Unknown error")
            print(f"❌ [ERROR] {message}")
            return False
        else:
            print(f"⚠️ [INFO] Response: {event_type}")
            return True
            
    except asyncio.TimeoutError:
        print("❌ [ERROR] Timeout khi chờ join room!")
        return False


async def host_mode(ws):
    """HOST mode - Tạo room hoặc join room, sau đó broadcast skin liên tục"""
    
    print_header("HOST", HARDCODED_TICKET)
    
    # Join room với ticket cứng
    success = await join_room_flow(ws, HARDCODED_TICKET)
    if not success:
        print("⚠️ [WARN] Join thất bại, thử tạo room mới...")
        ticket = await create_room_flow(ws)
        if not ticket:
            return
    
    print("\n" + "=" * 70)
    print("  🎮 HOST MODE - BROADCASTING SKINS")
    print("=" * 70)
    print("\n  Host sẽ broadcast skin mỗi 5 giây để test P2P sync")
    print("  Nhấn Ctrl+C để dừng.\n")
    
    skin_index = 0
    broadcast_count = 0
    
    # Tạo task để lắng nghe events
    async def listen_events():
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    event_type = data.get("event")
                    payload = data.get("data", {})
                    
                    if event_type == "PeerJoined":
                        peer_id = payload.get("peer_id", "Unknown")[:16]
                        print(f"\n  🟢 [PEER+] Teammate mới tham gia: {peer_id}...")
                        
                    elif event_type == "PeerLeft":
                        peer_id = payload.get("peer_id", "Unknown")[:16]
                        print(f"\n  🔴 [PEER-] Teammate đã rời: {peer_id}...")
                        
                    elif event_type == "RemoteSkinUpdate":
                        skin_name = payload.get("skin_name", "Unknown")
                        skin_id = payload.get("skin_id")
                        champion_id = payload.get("champion_id")
                        peer_id = payload.get("peer_id", "")[:16]
                        print(f"\n  📨 [RX] Nhận skin từ {peer_id}...")
                        print(f"      Champion: {champion_id}")
                        print(f"      Skin: {skin_name} (ID: {skin_id})")
                        
                    elif event_type == "SyncConfirmed":
                        peer_id = payload.get("peer_id", "Unknown")[:16]
                        print(f"\n  ✅ [ACK] {peer_id}... đã nhận skin của bạn")
                        
                    elif event_type == "Log":
                        level = payload.get("level", "INFO")
                        message = payload.get("message", "")
                        if level != "DEBUG":
                            print(f"  [{level}] {message}")
                            
                except json.JSONDecodeError:
                    pass
        except:
            pass
    
    # Start listener
    listener = asyncio.create_task(listen_events())
    
    try:
        while True:
            # Gửi skin
            skin = DEMO_SKINS[skin_index % len(DEMO_SKINS)]
            skin_info = skin["payload"]
            
            print(f"\n  📤 [TX #{broadcast_count + 1}] Broadcasting skin...")
            print(f"      Champion ID: {skin_info['champion_id']}")
            print(f"      Skin ID: {skin_info['skin_id']}")
            print(f"      Skin Name: {skin_info['skin_name']}")
            
            await ws.send(json.dumps(skin))
            
            broadcast_count += 1
            skin_index += 1
            
            # Đợi 5 giây trước khi gửi skin tiếp theo
            await asyncio.sleep(5)
            
    except asyncio.CancelledError:
        pass
    finally:
        listener.cancel()


async def default_mode(ws):
    """DEFAULT mode - Join room và lắng nghe skin updates"""
    
    print_header("DEFAULT (CLIENT)", HARDCODED_TICKET)
    
    # Join room với ticket cứng
    success = await join_room_flow(ws, HARDCODED_TICKET)
    if not success:
        print("❌ Không thể join room. Đảm bảo Host đang chạy.")
        return
    
    print("\n" + "=" * 70)
    print("  👀 DEFAULT MODE - LISTENING FOR SKINS")
    print("=" * 70)
    print("\n  Client đang lắng nghe skin updates từ Host...")
    print("  Sẽ tự động reply skin khi nhận được update")
    print("  Nhấn Ctrl+C để dừng.\n")
    
    received_count = 0
    
    try:
        async for message in ws:
            try:
                data = json.loads(message)
                event_type = data.get("event")
                payload = data.get("data", {})
                
                if event_type == "PeerJoined":
                    peer_id = payload.get("peer_id", "Unknown")[:16]
                    print(f"\n  🟢 [PEER+] Teammate tham gia: {peer_id}...")
                    
                elif event_type == "PeerLeft":
                    peer_id = payload.get("peer_id", "Unknown")[:16]
                    print(f"\n  🔴 [PEER-] Teammate rời đi: {peer_id}...")
                    
                elif event_type == "RemoteSkinUpdate":
                    received_count += 1
                    skin_name = payload.get("skin_name", "Unknown")
                    skin_id = payload.get("skin_id")
                    champion_id = payload.get("champion_id")
                    is_custom = payload.get("is_custom", False)
                    peer_id = payload.get("peer_id", "")[:16]
                    
                    print(f"\n  {'=' * 50}")
                    print(f"  📨 [RX #{received_count}] SKIN UPDATE từ {peer_id}...")
                    print(f"  {'=' * 50}")
                    print(f"      champion_id: {champion_id}")
                    print(f"      skin_id:     {skin_id}")
                    print(f"      skin_name:   {skin_name}")
                    print(f"      is_custom:   {is_custom}")
                    print(f"  {'=' * 50}")
                    
                    # Auto reply với skin khác
                    reply_index = received_count % len(DEMO_SKINS)
                    reply_skin = DEMO_SKINS[reply_index]
                    reply_info = reply_skin["payload"]
                    
                    print(f"\n  📤 [AUTO-REPLY] Gửi skin phản hồi...")
                    print(f"      Champion: {reply_info['champion_id']}")
                    print(f"      Skin: {reply_info['skin_name']}")
                    
                    await asyncio.sleep(1)  # Delay 1s trước khi reply
                    await ws.send(json.dumps(reply_skin))
                    
                elif event_type == "SyncConfirmed":
                    peer_id = payload.get("peer_id", "Unknown")[:16]
                    print(f"\n  ✅ [ACK] {peer_id}... đã nhận skin của bạn")
                    
                elif event_type == "Log":
                    level = payload.get("level", "INFO")
                    msg = payload.get("message", "")
                    if level in ["WARN", "ERROR"]:
                        print(f"  [{level}] {msg}")
                    
                else:
                    # Show other events for debugging
                    print(f"  [EVENT] {event_type}: {json.dumps(payload, ensure_ascii=False)}")
                    
            except json.JSONDecodeError:
                print(f"  [RAW] {message}")
                
    except websockets.exceptions.ConnectionClosed:
        print("\n❌ [DISCONNECTED] WebSocket đã đóng.")
    except Exception as e:
        print(f"\n❌ [ERROR] {e}")


async def start_sidecar():
    """Find and start sidecar binary"""
    sidecar_path = next((p for p in SEARCH_PATHS if p.exists()), None)
    
    if not sidecar_path:
        print(f"\n❌ [ERROR] Không tìm thấy sidecar binary ({BIN_NAME})")
        print("Đã tìm ở các đường dẫn:")
        for p in SEARCH_PATHS:
            print(f"    - {p}")
        return None
    
    print(f"\n🚀 [LAUNCH] Khởi động sidecar: {sidecar_path}")
    try:
        process = subprocess.Popen(
            [str(sidecar_path)],
            cwd=os.getcwd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("⏳ [WAIT] Chờ sidecar kết nối relay network (3s)...")
        await asyncio.sleep(3)
        return process
    except Exception as e:
        print(f"❌ [ERROR] Không thể khởi động sidecar: {e}")
        return None


async def connect_websocket():
    """Connect to sidecar WebSocket"""
    print(f"\n🔌 [CONNECT] Kết nối WebSocket: {WS_URI}")
    
    for attempt in range(5):
        try:
            ws = await websockets.connect(WS_URI, ping_interval=None)
            print("✅ [CONNECTED] WebSocket đã kết nối!")
            return ws
        except Exception as e:
            print(f"   Attempt {attempt+1}/5 failed: {e}")
            await asyncio.sleep(1)
    
    print("❌ [ERROR] Không thể kết nối WebSocket")
    return None


async def main():
    process = None
    ws = None
    
    while True:
        print_menu()
        
        try:
            choice = input("  Nhập lựa chọn [1/2/0]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break
        
        if choice == "0":
            print("\n👋 Goodbye!")
            break
        elif choice not in ["1", "2"]:
            print("\n⚠️ Lựa chọn không hợp lệ. Thử lại.\n")
            continue
        
        # Start sidecar if not running
        if process is None:
            process = await start_sidecar()
            if process is None:
                print("⚠️ Không thể khởi động sidecar. Thử lại.")
                continue
        
        # Connect WebSocket
        ws = await connect_websocket()
        if ws is None:
            print("⚠️ Không thể kết nối WebSocket. Kiểm tra sidecar.")
            if process:
                process.terminate()
                process = None
            continue
        
        try:
            if choice == "1":
                await host_mode(ws)
            else:
                await default_mode(ws)
                
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            print("\n\n⏹️ [STOP] Dừng bởi người dùng...")
        finally:
            if ws:
                try:
                    await ws.close()
                except:
                    pass
                ws = None
    
    # Cleanup
    if ws:
        try:
            await ws.close()
        except:
            pass
    
    if process:
        print("\n🧹 [CLEANUP] Đang đóng sidecar...")
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    
    print("✅ [DONE] Hoàn tất!")


if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
