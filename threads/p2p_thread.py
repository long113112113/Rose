#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2P Sidecar Thread
Runs the asyncio loop for the P2P client
"""

import asyncio
import threading
from utils.integration.p2p_client import p2p_client
from utils.core.logging import get_logger

log = get_logger()

class P2PThread(threading.Thread):
    """
    Background thread for running P2P client asyncio loop.
    """

    def __init__(self, state):
        super().__init__(daemon=True, name="P2PThread")
        self.state = state
        self.loop = None

    def run(self):
        """Run the asyncio loop"""
        log.info("Starting P2P Client Thread")
        
        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            # Start p2p client (which starts the process and connects)
            # We assume sidecar management is handled here by default
            self.loop.run_until_complete(p2p_client.start(manage_process=False))
            
            # Run the loop forever to handle tasks
            self.loop.run_forever()
        except Exception as e:
            log.error(f"P2P Thread crashed: {e}")
        finally:
            self.loop.close()

    def stop(self):
        """Stop the thread"""
        if self.loop:
            # Schedule stop on the loop
            self.loop.call_soon_threadsafe(p2p_client.stop)
            self.loop.call_soon_threadsafe(self.loop.stop)
