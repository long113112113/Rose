#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2P Coordinator (NodeMaster version)
Simplified P2P connection setup via NodeMaster server.
No longer uses party chat - all peer discovery is handled by NodeMaster.
"""

import hashlib
from typing import Optional, TYPE_CHECKING

from utils.core.logging import get_logger
from config import NODEMASTER_URL

if TYPE_CHECKING:
    from utils.integration.p2p_client import P2PClient
    from state import SharedState

log = get_logger()


class P2PCoordinator:
    """Simplified P2P coordinator using NodeMaster for peer discovery"""

    # Phases where P2P is active (in lobby or champ select, ready to sync skins)
    ACTIVE_PHASES = ("Lobby", "ChampSelect", "None", None)
    
    # Phases where P2P should disconnect (game in progress, no sync needed)
    DISCONNECT_PHASES = ("InProgress", "WaitingForStats", "EndOfGame", "Reconnect")

    def __init__(self, p2p_client: "P2PClient", state: "SharedState"):
        """Initialize P2P coordinator

        Args:
            p2p_client: P2P client instance
            state: Shared application state
        """
        self.p2p_client = p2p_client
        self.state = state

        self._current_party_id: Optional[str] = None
        self._current_ticket: Optional[str] = None
        self._is_active = True
        self._is_connected = False  # Track P2P connection state

        # NodeMaster URL from config
        self._nodemaster_url = NODEMASTER_URL

    def is_active(self) -> bool:
        """Check if P2P coordinator should be active based on phase"""
        return self.state.phase in self.ACTIVE_PHASES

    async def on_phase_change(self, new_phase: str):
        """Handle phase changes - disconnect when entering game, reconnect when back to lobby

        Args:
            new_phase: The new gameflow phase
        """
        was_active = self._is_active
        self._is_active = new_phase in self.ACTIVE_PHASES

        # Disconnect when entering game phases to reduce load
        if new_phase in self.DISCONNECT_PHASES and self._is_connected:
            log.info(f"[P2P] Entering {new_phase}, disconnecting to reduce load")
            self.p2p_client.leave_room_sync()
            self._is_connected = False
        
        # Reconnect when returning to Lobby (if we have a party)
        elif new_phase in self.ACTIVE_PHASES and not self._is_connected and self._current_party_id:
            log.info(f"[P2P] Returning to {new_phase}, reconnecting to party")
            self.p2p_client.join_via_nodemaster_sync(
                ticket=self._current_ticket,
                nodemaster_url=self._nodemaster_url
            )
            self._is_connected = True

        if was_active and not self._is_active:
            log.debug(f"[P2P] Phase inactive: {new_phase}")
        elif not was_active and self._is_active:
            log.debug(f"[P2P] Phase active: {new_phase}")

    async def on_lobby_join(self, party_id: str):
        """Called when user joins a lobby

        With NodeMaster, both host and guest use the same flow.
        The NodeMaster server handles peer discovery.

        Args:
            party_id: The party ID from LCU
        """
        if not self.is_active():
            log.debug("[P2P] Not in active phase, skipping lobby join")
            return

        # Skip if already connected to same party
        if party_id == self._current_party_id and self._is_connected:
            log.debug(f"[P2P] Already connected to party {party_id[:8]}..., skipping")
            return

        # If switching parties, leave the old room first
        if self._is_connected and self._current_party_id and self._current_party_id != party_id:
            log.info(f"[P2P] Switching party, leaving old room first")
            self.p2p_client.leave_room_sync()
            self._is_connected = False

        # Create ticket from party ID hash
        ticket = hashlib.sha256(party_id.encode()).hexdigest()

        self._current_party_id = party_id
        self._current_ticket = ticket

        log.info(f"[P2P] Joining party via NodeMaster: {party_id[:8]}...")

        # Send join command to sidecar
        # Sidecar will handle NodeMaster connection and peer discovery
        self.p2p_client.join_via_nodemaster_sync(
            ticket=ticket,
            nodemaster_url=self._nodemaster_url
        )
        self._is_connected = True

    async def on_lobby_leave(self):
        """Called when user leaves the lobby"""
        if self._current_party_id:
            log.info(f"[P2P] Left party {self._current_party_id[:8]}...")
            self._current_party_id = None
            self._current_ticket = None
            self._is_connected = False
            # Notify sidecar to leave P2P room
            self.p2p_client.leave_room_sync()

    def reset(self):
        """Reset coordinator state and leave P2P room"""
        if self._is_connected:
            # Notify sidecar to leave P2P room
            self.p2p_client.leave_room_sync()
        self._current_party_id = None
        self._current_ticket = None
        self._is_connected = False
        log.debug("[P2P] Coordinator state reset")

