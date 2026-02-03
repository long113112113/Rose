
import asyncio
import json
import logging
import websockets
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s | %(levelname)s | %(message)s'
)
log = logging.getLogger(__name__)

# Constants
P2P_PORT = 13337

async def mock_p2p_server():
    """Starts a mock P2P server that mimics the Sidecar for testing UI Sync"""
    
    print("\n" + "="*50)
    print(" ROSE P2P MOCK SIDECAR - TESTING TOOL ")
    print("="*50)
    
    party_id = input("Enter Room ID (PartyID) to simulate: ").strip() or "mock-party-123"
    peer_name = input("Enter Mock Peer Name (e.g. Player2): ").strip() or "MockPlayer"
    
    print(f"\nConfigured: Room {party_id} | Peer {peer_name}")
    print(f"Server will listen on port {P2P_PORT}")
    print("="*50 + "\n")

    async def handler(websocket, path):
        log.info(f"App connected to mock Sidecar")
        
        # 1. Simulate joining the room
        await websocket.send(json.dumps({
            "event": "PeerJoined",
            "data": {"peer_id": peer_name}
        }))
        log.info(f"Sent: PeerJoined -> {peer_name}")

        # 2. Simulate a remote skin update (Hardcoded Braum Bán Kebab)
        # We wait 3 seconds to let the App stabilize
        await asyncio.sleep(3)
        
        braum_payload = {
            "event": "RemoteSkinUpdate",
            "data": {
                "peer_id": peer_name,
                "champion_id": 201,
                "skin_id": 201042,
                "skin_name": "Braum Bán Kebab",
                "is_custom": False
            }
        }
        await websocket.send(json.dumps(braum_payload))
        log.info(f"Sent: RemoteSkinUpdate (Braum Bán Kebab) from {peer_name}")

        try:
            async for message in websocket:
                data = json.loads(message)
                action = data.get("action")
                payload = data.get("payload")
                
                if action == "UpdateSkin":
                    log.info(f"App is broadcasting skin change: {payload.get('skin_name')} (ID: {payload.get('skin_id')})")
                    
                    # 3. Simulate ACK (Sync Confirmation) from the Mock Peer
                    await asyncio.sleep(0.8) # Tiny delay for realism
                    ack_payload = {
                        "event": "SyncConfirmed",
                        "data": {"peer_id": peer_name}
                    }
                    await websocket.send(json.dumps(ack_payload))
                    log.info(f"Sent: SyncConfirmed from {peer_name}")

                elif action == "JoinRoom":
                    log.info(f"App requested to join room: {payload}")
                    # Sidecar usually doesn't need to reply to this for the Python app logic to continue
                    
        except websockets.exceptions.ConnectionClosed:
            log.info("App disconnected")

    log.info(f"Starting mock P2P server on 127.0.0.1:{P2P_PORT}")
    try:
        async with websockets.serve(handler, "127.0.0.1", P2P_PORT):
            await asyncio.Future()  # run forever
    except Exception as e:
        log.error(f"Failed to start server: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(mock_p2p_server())
    except KeyboardInterrupt:
        print("\nStopping mock server...")
