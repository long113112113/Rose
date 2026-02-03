#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2P Handler
Handles P2P event logic and skin synchronization
"""

import json
from typing import Optional

from state import SharedState
from utils.core.logging import get_logger
from utils.integration.p2p_client import p2p_client

log = get_logger()


class P2PHandler:
    """Handles P2P event logic and skin synchronization"""

    def __init__(self, state: SharedState):
        """Initialize P2P handler

        Args:
            state: Shared application state
        """
        self.state = state
        self.state.active_peers = set()
        self._debounce_timer = None
        self._register_callbacks()

    def _register_callbacks(self):
        """Register P2P event callbacks"""
        p2p_client.on("RemoteSkinUpdate", self.handle_skin_update)
        p2p_client.on("SyncConfirmed", self.handle_skin_ack)
        p2p_client.on("PeerJoined", self.handle_peer_joined)
        p2p_client.on("PeerLeft", self.handle_peer_left)

    async def handle_peer_joined(self, payload: dict):
        """Handle new peer connection from Sidecar"""
        peer_id = payload.get("peer_id")
        if peer_id:
            self.state.active_peers.add(peer_id)
        log.info(f"[P2P] Peer joined: {peer_id} (Total: {len(self.state.active_peers)})")
        self._broadcast_connection_state()

    async def handle_peer_left(self, payload: dict):
        """Handle peer disconnection from Sidecar"""
        peer_id = payload.get("peer_id")
        log.info(f"[P2P] Peer left: {peer_id}")
        if peer_id:
            if peer_id in self.state.active_peers:
                 self.state.active_peers.remove(peer_id)
            if peer_id in self.state.peer_skins:
                 del self.state.peer_skins[peer_id]
        self._broadcast_connection_state()

    def _broadcast_connection_state(self):
        """Broadcast P2P connection state to UI"""
        if hasattr(self.state, "ui_skin_thread") and self.state.ui_skin_thread:
            try:
                is_connected = self.state.current_party_id is not None
                
                peer_count = len(self.state.active_peers) 
                
                self.state.ui_skin_thread._broadcast_p2p_connection_state(
                    is_connected=is_connected,
                    peer_count=peer_count,
                    party_id=self.state.current_party_id
                )
            except Exception as e:
                log.debug(f"[P2P] Failed to broadcast connection state: {e}")

    async def handle_skin_update(self, payload: dict):
        """Handle incoming skin update from peer"""
        try:
            peer_id = payload.get("peer_id")
            if not peer_id:
                return

            log.info(f"[P2P] Received skin update from {peer_id}: {payload}")

            self.state.peer_skins[peer_id] = payload

            # Trigger UI update
            if hasattr(self.state, "ui_skin_thread") and self.state.ui_skin_thread:
                 try:
                     self.state.ui_skin_thread._broadcast_peer_update(payload)
                 except Exception as e:
                     log.debug(f"[P2P] Failed to broadcast peer update to UI: {e}")

        except Exception as e:
            log.error(f"[P2P] Error handling RemoteSkinUpdate: {e}")

    async def handle_skin_ack(self, payload: dict):
        """Handle incoming skin ACK confirmation from Sidecar"""
        try:
            sender_peer_id = payload.get("peer_id")
            log.info(f"[P2P] Logic confirmation: {sender_peer_id} synced our skin")

            # Notify UI that this peer is synced
            if hasattr(self.state, "ui_skin_thread") and self.state.ui_skin_thread:
                 self.state.ui_skin_thread._broadcast_peer_ack(sender_peer_id, "ME")

        except Exception as e:
             log.error(f"[P2P] Error handling SyncConfirmed: {e}")

    def broadcast_skin_change(self, champion_id: int, skin_id: int, skin_name: str, is_custom: bool = False):
        """Broadcast local skin change to P2P network (Debounced)"""
        import threading
        
        payload = {
            "champion_id": champion_id,
            "skin_id": skin_id,
            "skin_name": skin_name,
            "is_custom": is_custom
        }
        if is_custom or self.state.selected_custom_mod:
            return

        # Debounce: 0.5s
        if hasattr(self, "_debounce_timer") and self._debounce_timer:
            self._debounce_timer.cancel()
        
        # Define the function to run after delay
        def _do_send():
            p2p_client.send_action_sync("UpdateSkin", payload)
            log.info(f"[P2P] Broadcasted skin change: {payload}")
            self._debounce_timer = None

        # Start new timer
        self._debounce_timer = threading.Timer(0.5, _do_send)
        self._debounce_timer.start()
