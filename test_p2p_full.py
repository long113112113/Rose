"""
Full P2P Test Client (via Sidecar)
Tests actual P2P messaging through iroh-gossip

Usage:
    Terminal 1: python test_p2p_full.py host
    Terminal 2: python test_p2p_full.py join

This will:
1. Start the sidecar (if not running)
2. Connect via NodeMaster for peer discovery
3. Exchange messages via iroh-gossip P2P
4. Show connection mode (direct/relay)
"""

import asyncio
import json
import hashlib
import sys
import time
import websockets

# Configuration
SIDECAR_URL = "ws://127.0.0.1:13337"
NODEMASTER_URL = "ws://14.225.206.162:31337"
TEST_ROOM = "p2p_test_room_12345"

class P2PTestClient:
    def __init__(self, mode: str):
        self.mode = mode  # "host" or "join"
        self.ws = None
        self.node_id = None
        self.peers = []
        self.connected = False
        
    async def connect(self):
        """Connect to sidecar WebSocket"""
        print(f"\n{'='*60}")
        print(f"P2P Full Test Client - Mode: {self.mode.upper()}")
        print(f"{'='*60}")
        print(f"Sidecar:    {SIDECAR_URL}")
        print(f"NodeMaster: {NODEMASTER_URL}")
        print(f"Room:       {TEST_ROOM}")
        print(f"{'='*60}\n")
        
        try:
            self.ws = await websockets.connect(SIDECAR_URL, ping_interval=None)
            print("✅ Connected to Sidecar!")
            self.connected = True
            return True
        except ConnectionRefusedError:
            print("❌ Cannot connect to Sidecar!")
            print("   Make sure sidecar.exe is running:")
            print("   d:\\Rose\\sidecar\\target\\release\\sidecar.exe")
            return False
    
    async def get_node_id(self):
        """Get our node ID from sidecar"""
        await self.send_action("GetNodeId", None)
        
    async def join_room(self):
        """Join P2P room via NodeMaster"""
        ticket = hashlib.sha256(TEST_ROOM.encode()).hexdigest()
        payload = {
            "ticket": ticket,
            "nodemaster_url": NODEMASTER_URL
        }
        await self.send_action("JoinViaNodeMaster", payload)
        print(f"📤 Joining room via NodeMaster...")
        print(f"   Ticket: {ticket[:16]}...")
        
    async def send_message(self, msg: str):
        """Send a gossip message to all peers"""
        payload = {
            "data": msg
        }
        await self.send_action("Broadcast", payload)
        print(f"📤 Sent message: {msg}")
        
    async def send_action(self, action: str, payload):
        """Send action to sidecar"""
        msg = {
            "action": action,
            "payload": payload
        }
        await self.ws.send(json.dumps(msg))
        
    async def handle_events(self):
        """Handle incoming events from sidecar"""
        try:
            async for message in self.ws:
                data = json.loads(message)
                event = data.get("event", "unknown")
                payload = data.get("data")
                
                if event == "NodeId":
                    self.node_id = payload
                    print(f"\n🆔 Our Node ID: {payload[:32]}...")
                    
                elif event == "JoinedRoom":
                    print(f"\n🚪 Joined room successfully!")
                    if payload:
                        print(f"   Topic: {payload.get('topic', 'N/A')[:16]}...")
                    
                elif event == "NeighborUp":
                    peer_id = payload.get("node_id", "unknown") if payload else "unknown"
                    self.peers.append(peer_id)
                    print(f"\n🟢 PEER CONNECTED: {peer_id[:32]}...")
                    print(f"   Total peers: {len(self.peers)}")
                    
                    # Show connection info if available
                    if payload:
                        conn_type = payload.get("connection_type", "unknown")
                        if conn_type:
                            print(f"   Connection: {conn_type}")
                    
                    # Send test message when peer joins
                    if self.mode == "host":
                        await asyncio.sleep(1)
                        await self.send_message(f"Hello from HOST! Time: {time.strftime('%H:%M:%S')}")
                        
                elif event == "NeighborDown":
                    peer_id = payload.get("node_id", "unknown") if payload else "unknown"
                    if peer_id in self.peers:
                        self.peers.remove(peer_id)
                    print(f"\n🔴 PEER DISCONNECTED: {peer_id[:32]}...")
                    print(f"   Remaining peers: {len(self.peers)}")
                    
                elif event == "GossipMessage":
                    sender = payload.get("from", "unknown")[:16] if payload else "unknown"
                    content = payload.get("content", "") if payload else ""
                    print(f"\n💬 MESSAGE RECEIVED")
                    print(f"   From: {sender}...")
                    print(f"   Content: {content}")
                    
                    # Reply if we're not host
                    if self.mode != "host" and "Hello from HOST" in content:
                        await asyncio.sleep(0.5)
                        await self.send_message(f"Hello back from CLIENT! Time: {time.strftime('%H:%M:%S')}")
                        
                elif event == "ConnectionInfo":
                    # Connection mode info
                    if payload:
                        mode = payload.get("mode", "unknown")
                        relay = payload.get("relay_url", None)
                        latency = payload.get("latency_ms", None)
                        print(f"\n📡 CONNECTION INFO")
                        print(f"   Mode: {mode}")
                        if relay:
                            print(f"   Relay: {relay}")
                        if latency:
                            print(f"   Latency: {latency}ms")
                            
                elif event == "Error":
                    print(f"\n❌ ERROR: {payload}")
                    
                elif event == "LeftRoom":
                    print(f"\n👋 Left room")
                    
                else:
                    print(f"\n📨 Event: {event}")
                    if payload:
                        print(f"   Data: {json.dumps(payload, indent=2)[:200]}")
                        
        except websockets.exceptions.ConnectionClosed:
            print("\n⚠️ Connection to sidecar closed")
        except KeyboardInterrupt:
            print("\n\n👋 Exiting...")
            
    async def run(self):
        """Main run loop"""
        if not await self.connect():
            return
            
        # Get our node ID first
        await self.get_node_id()
        await asyncio.sleep(0.5)
        
        # Join the test room
        await self.join_room()
        
        print(f"\n{'='*60}")
        print("Waiting for events... (Ctrl+C to exit)")
        print("Messages will be exchanged automatically when peers connect")
        print(f"{'='*60}\n")
        
        # Handle events
        await self.handle_events()


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "join"
    
    if mode not in ["host", "join"]:
        print("Usage: python test_p2p_full.py [host|join]")
        print("  host - First client (will send greeting)")
        print("  join - Second client (will reply)")
        return
        
    client = P2PTestClient(mode)
    await client.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
