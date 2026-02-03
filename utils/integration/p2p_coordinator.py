#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2P Coordinator
Coordinates P2P connection setup via LCU party chat
Only active during Lobby phase for performance
"""

import asyncio
import hashlib
from typing import Optional, TYPE_CHECKING

from utils.core.logging import get_logger

if TYPE_CHECKING:
    from lcu import LCU
    from utils.integration.p2p_client import P2PClient
    from state import SharedState

log = get_logger()


class P2PCoordinator:
    """Coordinates P2P connection setup via party chat"""

    # Phases where P2P chat exchange is active
    ACTIVE_PHASES = ("Lobby", "None", None)
    # Phases where P2P chat exchange is disabled for performance
    INACTIVE_PHASES = ("ChampSelect", "InProgress", "WaitingForStats", "EndOfGame")

    def __init__(self, lcu: "LCU", p2p_client: "P2PClient", state: "SharedState"):
        """Initialize P2P coordinator

        Args:
            lcu: LCU client instance
            p2p_client: P2P client instance
            state: Shared application state
        """
        self.lcu = lcu
        self.p2p_client = p2p_client
        self.state = state

        self._is_host = False
        self._known_endpoints: list[tuple[int, str]] = []  # List of (index, node_id)
        self._my_node_id: Optional[str] = None
        self._current_ticket: Optional[str] = None
        self._my_endpoint_index = 0
        self._is_active = True
        self._current_party_id: Optional[str] = None

    def is_active(self) -> bool:
        """Check if P2P coordinator should be active based on phase"""
        return self.state.phase in self.ACTIVE_PHASES

    async def on_phase_change(self, new_phase: str):
        """Handle phase changes for performance optimization

        Args:
            new_phase: The new gameflow phase
        """
        was_active = self._is_active
        self._is_active = new_phase in self.ACTIVE_PHASES

        if was_active and not self._is_active:
            log.info(f"[P2P] Pausing P2P chat listener - phase: {new_phase}")
        elif not was_active and self._is_active:
            log.info(f"[P2P] Resuming P2P chat listener - phase: {new_phase}")

    async def on_lobby_join(self, party_id: str, is_leader: bool):
        """Called when user joins a lobby

        Args:
            party_id: The party ID from LCU
            is_leader: Whether local player is party leader
        """
        if not self.is_active():
            log.debug("[P2P] Not in active phase, skipping lobby join handler")
            return

        # Reset state for new party
        if party_id != self._current_party_id:
            self._known_endpoints = []
            self._current_ticket = None
            self._my_endpoint_index = 0
            self._current_party_id = party_id

        self._is_host = is_leader

        # Get my node ID from sidecar
        if not self._my_node_id:
            self._my_node_id = await self.p2p_client.get_node_id()
            if not self._my_node_id:
                log.warning("[P2P] Failed to get node ID from sidecar")
                return

        log.info(f"[P2P] Lobby join - party: {party_id[:8]}..., host: {is_leader}")

        if is_leader:
            await self._handle_host_join(party_id)
        else:
            await self._handle_guest_join()

    async def _handle_host_join(self, party_id: str):
        """Handle joining as party host/leader

        Args:
            party_id: The party ID
        """
        # Create ticket from party ID hash
        topic_hash = hashlib.sha256(party_id.encode()).hexdigest()
        self._current_ticket = f"{topic_hash}|{self._my_node_id}"

        # Host is always endpoint 1
        self._my_endpoint_index = 1
        self._known_endpoints = [(1, self._my_node_id)]

        # Join the gossip room
        self.p2p_client.send_action_sync("JoinTicket", self._current_ticket)

        # Broadcast to party chat
        await self._broadcast_all_info()

        log.info(f"[P2P] Host created room: {topic_hash[:16]}...")

    async def _handle_guest_join(self):
        """Handle joining as guest (non-host)"""
        # Read chat to get P2P info from host
        p2p_info = self.lcu.get_party_p2p_info(host_only=True)

        ticket = p2p_info.get("ticket")
        endpoints = p2p_info.get("endpoints", [])

        if not ticket:
            log.warning("[P2P] No ticket found in party chat, waiting for host to broadcast")
            return

        self._current_ticket = ticket

        # Sync endpoints from host
        self._sync_endpoints_from_host(endpoints)

        # Determine my endpoint index (next available)
        existing_indices = [idx for idx, _ in self._known_endpoints]
        self._my_endpoint_index = max(existing_indices, default=0) + 1

        # Add myself to known endpoints
        self._known_endpoints.append((self._my_endpoint_index, self._my_node_id))

        # Join the gossip room with ticket
        self.p2p_client.send_action_sync("JoinTicket", ticket)

        # Send my endpoint to chat
        self.lcu.send_party_endpoint(self._my_node_id, self._my_endpoint_index)

        log.info(f"[P2P] Guest joined room, endpoint index: {self._my_endpoint_index}")

    async def on_member_join(self, summoner_id: str):
        """Called when a new member joins party (Host only)

        Args:
            summoner_id: The new member's summoner ID
        """
        if not self._is_host or not self.is_active():
            return

        log.info(f"[P2P] New member joined, re-broadcasting P2P info")

        # Re-broadcast all info for new member
        await self._broadcast_all_info()

    async def on_chat_message(self, message: dict):
        """Called when party chat message received

        Args:
            message: The chat message dict from LCU event
        """
        if not self.is_active():
            return

        body = message.get("body", "")

        # Only process Rose protocol messages
        if not body.startswith("[ROSE-"):
            return

        # If I'm host, process new endpoint registrations
        if self._is_host:
            await self._process_guest_endpoint(message)
        else:
            # If I'm guest, update from host messages
            host_id = self.lcu.party_chat.get_host_summoner_id()
            if str(message.get("fromSummonerId")) == str(host_id):
                await self._process_host_message(message)

    async def _process_guest_endpoint(self, message: dict):
        """Process endpoint registration from guest

        Args:
            message: The chat message dict
        """
        body = message.get("body", "")

        # Parse endpoint message: [ROSE-EP:N]:nodeId
        if body.startswith("[ROSE-EP:"):
            import re
            match = re.match(r"\[ROSE-EP:(\d+)\]:(.+)", body)
            if match:
                idx = int(match.group(1))
                node_id = match.group(2)

                # Check if this is a new endpoint
                existing_ids = [nid for _, nid in self._known_endpoints]
                if node_id not in existing_ids and node_id != self._my_node_id:
                    self._known_endpoints.append((idx, node_id))
                    log.info(f"[P2P] Host: Added new endpoint {idx}: {node_id[:16]}...")

                    # Re-broadcast with new endpoint
                    await self._broadcast_all_info()

    async def _process_host_message(self, message: dict):
        """Process message from host to update local state

        Args:
            message: The chat message dict
        """
        body = message.get("body", "")

        # Parse ticket
        if body.startswith("[ROSE-TICKET]:"):
            ticket = body[len("[ROSE-TICKET]:"):]
            if ticket != self._current_ticket:
                self._current_ticket = ticket
                # Re-join with new ticket
                self.p2p_client.send_action_sync("JoinTicket", ticket)
                log.info(f"[P2P] Updated ticket from host")

        # Parse endpoint
        elif body.startswith("[ROSE-EP:"):
            import re
            match = re.match(r"\[ROSE-EP:(\d+)\]:(.+)", body)
            if match:
                idx = int(match.group(1))
                node_id = match.group(2)

                # Sync this endpoint
                existing_ids = [nid for _, nid in self._known_endpoints]
                if node_id not in existing_ids and node_id != self._my_node_id:
                    self._known_endpoints.append((idx, node_id))
                    log.info(f"[P2P] Added peer from host: {node_id[:16]}...")

    def _sync_endpoints_from_host(self, received_endpoints: list):
        """Compare and update local endpoints with Host's broadcast

        Args:
            received_endpoints: List of (index, node_id) tuples from host
        """
        for idx, node_id in received_endpoints:
            # Skip my own endpoint
            if node_id == self._my_node_id:
                continue

            # Check if already known
            existing_ids = [nid for _, nid in self._known_endpoints]
            if node_id not in existing_ids:
                self._known_endpoints.append((idx, node_id))
                log.info(f"[P2P] Synced endpoint {idx}: {node_id[:16]}...")

    async def _broadcast_all_info(self):
        """Host broadcasts ticket and all known endpoints"""
        if not self._is_host or not self._current_ticket:
            return

        success = self.lcu.broadcast_party_p2p_info(
            self._current_ticket,
            self._known_endpoints
        )

        if success:
            log.info(f"[P2P] Broadcast: ticket + {len(self._known_endpoints)} endpoints")
        else:
            log.warning("[P2P] Failed to broadcast P2P info")

    def reset(self):
        """Reset coordinator state (e.g., when leaving party)"""
        self._is_host = False
        self._known_endpoints = []
        self._current_ticket = None
        self._my_endpoint_index = 0
        self._current_party_id = None
        log.debug("[P2P] Coordinator state reset")
