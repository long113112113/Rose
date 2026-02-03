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
        self._register_callbacks()

    def _register_callbacks(self):
        """Register P2P event callbacks"""
        p2p_client.on("SkinUpdate", self.handle_skin_update)

    async def handle_skin_update(self, payload: dict):
        """Handle incoming skin update from peer"""
        try:
            peer_id = payload.get("peerId") or payload.get("summonerId")  # Use whatever ID we get
            if not peer_id:
                log.warning("[P2P] Received SkinUpdate without peer identification")
                return

            log.info(f"[P2P] Received skin update from {peer_id}: {payload}")

            # Update shared state
            # We assume payload contains: championId, skinId, isCustom, skinName, etc.
            self.state.peer_skins[peer_id] = payload

            # Trigger UI update if needed (e.g. via broadcasting to JS)
            if hasattr(self.state, "ui_skin_thread") and self.state.ui_skin_thread:
                 # Check if this peer is in our game/lobby and update UI accordingly
                 # For now, just logging it is enough as a start.
                 # Eventually we might want to emit a specific event to JS.
                 pass

        except Exception as e:
            log.error(f"[P2P] Error handling SkinUpdate: {e}")

    def broadcast_skin_change(self, champion_id: int, skin_id: int, skin_name: str, is_custom: bool = False):
        """Broadcast local skin change to P2P network"""
        payload = {
            "championId": champion_id,
            "skinId": skin_id,
            "skinName": skin_name,
            "isCustom": is_custom
        }
        
        # If we have a custom mod selected, include more info?
        if is_custom and self.state.selected_custom_mod:
             payload["modName"] = self.state.selected_custom_mod.get("mod_name")

        # Send via P2P client
        # We use send_action_sync because this might be called from non-async threads (UI thread)
        p2p_client.send_action_sync("SkinUpdate", payload)
        log.info(f"[P2P] Broadcasted skin change: {payload}")
