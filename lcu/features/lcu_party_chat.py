#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Party Chat for P2P Endpoint Exchange
Manages sending and parsing Rose protocol messages in party chat
"""

from typing import Optional
import re

from utils.core.logging import get_logger

log = get_logger()


class LCUPartyChat:
    """Manages P2P endpoint exchange via party chat"""

    PREFIX_TICKET = "[ROSE-TICKET]:"
    PREFIX_ENDPOINT = "[ROSE-EP:"

    def __init__(self, api):
        """Initialize party chat handler

        Args:
            api: LCUAPI instance
        """
        self._api = api

    def get_party_conversation_id(self) -> Optional[str]:
        """Get the conversation ID for current party/lobby chat

        Returns:
            Conversation ID string, or None if not in a party
        """
        conversations = self._api.get("/lol-chat/v1/conversations")
        if not conversations:
            return None

        # Find party/lobby conversation
        for conv in conversations:
            conv_type = conv.get("type", "")
            # Party chat types: "championSelect", "lobby", "customGame"
            if conv_type in ("championSelect", "lobby", "customGame"):
                return conv.get("id")

        return None

    def get_chat_messages(self, conversation_id: str) -> list:
        """Get messages from a conversation

        Args:
            conversation_id: The conversation ID

        Returns:
            List of message dicts
        """
        messages = self._api.get(f"/lol-chat/v1/conversations/{conversation_id}/messages")
        return messages if messages else []

    def send_message(self, conversation_id: str, body: str) -> bool:
        """Send a message to a conversation

        Args:
            conversation_id: The conversation ID
            body: Message content

        Returns:
            True if successful
        """
        resp = self._api.post(
            f"/lol-chat/v1/conversations/{conversation_id}/messages",
            {"body": body, "type": "chat"},
            timeout=2.0
        )
        if resp and resp.status_code in (200, 201):
            log.debug(f"[PartyChat] Sent message: {body[:50]}...")
            return True
        log.warning(f"[PartyChat] Failed to send message: {resp.status_code if resp else 'None'}")
        return False

    def send_ticket(self, ticket: str) -> bool:
        """Send ticket to party chat (Host only)

        Args:
            ticket: The gossip ticket (topic|nodeId format)

        Returns:
            True if successful
        """
        conv_id = self.get_party_conversation_id()
        if not conv_id:
            log.warning("[PartyChat] Cannot send ticket - no party conversation")
            return False

        message = f"{self.PREFIX_TICKET}{ticket}"
        return self.send_message(conv_id, message)

    def send_endpoint(self, endpoint_id: str, index: int) -> bool:
        """Send endpoint ID to party chat

        Args:
            endpoint_id: The node ID to share
            index: Endpoint index (1 for host, 2+ for others)

        Returns:
            True if successful
        """
        conv_id = self.get_party_conversation_id()
        if not conv_id:
            log.warning("[PartyChat] Cannot send endpoint - no party conversation")
            return False

        message = f"{self.PREFIX_ENDPOINT}{index}]:{endpoint_id}"
        return self.send_message(conv_id, message)

    def broadcast_all_endpoints(self, ticket: str, endpoints: list, my_index: int = 1) -> bool:
        """Host broadcasts ticket and all known endpoints

        Args:
            ticket: The gossip ticket
            endpoints: List of (index, endpoint_id) tuples
            my_index: Host's own endpoint index (usually 1)

        Returns:
            True if all messages sent successfully
        """
        conv_id = self.get_party_conversation_id()
        if not conv_id:
            log.warning("[PartyChat] Cannot broadcast - no party conversation")
            return False

        success = True

        # Send ticket first
        if not self.send_message(conv_id, f"{self.PREFIX_TICKET}{ticket}"):
            success = False

        # Send all endpoints
        for idx, ep_id in endpoints:
            msg = f"{self.PREFIX_ENDPOINT}{idx}]:{ep_id}"
            if not self.send_message(conv_id, msg):
                success = False

        return success

    def parse_rose_messages(self, messages: list, host_summoner_id: Optional[str] = None) -> dict:
        """Parse Rose protocol messages from chat history

        Args:
            messages: List of message dicts from LCU
            host_summoner_id: If provided, only parse messages from this sender (Host)

        Returns:
            Dict with 'ticket' and 'endpoints' list
        """
        result = {
            "ticket": None,
            "endpoints": []  # List of (index, node_id) tuples
        }

        # Pattern for endpoint messages: [ROSE-EP:N]:nodeId
        endpoint_pattern = re.compile(r"\[ROSE-EP:(\d+)\]:(.+)")

        for msg in messages:
            body = msg.get("body", "")
            sender_id = msg.get("fromSummonerId")

            # If host filter is set, only accept messages from host
            if host_summoner_id and str(sender_id) != str(host_summoner_id):
                continue

            # Parse ticket
            if body.startswith(self.PREFIX_TICKET):
                result["ticket"] = body[len(self.PREFIX_TICKET):]
                log.debug(f"[PartyChat] Found ticket: {result['ticket'][:30]}...")

            # Parse endpoint
            match = endpoint_pattern.match(body)
            if match:
                idx = int(match.group(1))
                node_id = match.group(2)
                result["endpoints"].append((idx, node_id))
                log.debug(f"[PartyChat] Found endpoint {idx}: {node_id[:20]}...")

        return result

    def get_host_summoner_id(self) -> Optional[str]:
        """Get the summoner ID of the party host/leader

        Returns:
            Host's summoner ID as string, or None
        """
        lobby = self._api.get("/lol-lobby/v2/lobby")
        if not lobby:
            return None

        # Find leader in members
        members = lobby.get("members", [])
        for member in members:
            if member.get("isLeader", False):
                return str(member.get("summonerId"))

        return None

    def am_i_host(self) -> bool:
        """Check if local player is the party host

        Returns:
            True if local player is leader
        """
        lobby = self._api.get("/lol-lobby/v2/lobby")
        if not lobby:
            return False

        local_member = lobby.get("localMember", {})
        return local_member.get("isLeader", False)
