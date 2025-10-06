#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System tray manager for SkinCloner
"""

import os
import sys
import threading
import ctypes
from ctypes import wintypes
from typing import Optional, Callable
import pystray
from PIL import Image, ImageDraw
from utils.logging import get_logger

log = get_logger()


class TrayManager:
    """Manages the system tray icon for SkinCloner"""
    
    def __init__(self, quit_callback: Optional[Callable] = None):
        """
        Initialize the tray manager
        
        Args:
            quit_callback: Function to call when user clicks "Quit"
        """
        self.quit_callback = quit_callback
        self.icon = None
        self.tray_thread = None
        self._stop_event = threading.Event()
        self._is_downloading = False
        self._base_icon_image = None
        
    def _create_icon_image(self) -> Image.Image:
        """Create a simple icon image for the tray"""
        # Create a 64x64 icon with a simple design
        width, height = 64, 64
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Draw a simple "SC" logo (SkinCloner)
        # Background circle
        draw.ellipse([8, 8, 56, 56], fill=(0, 100, 200, 255), outline=(0, 50, 100, 255), width=2)
        
        # "SC" text
        try:
            # Try to use a font if available
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            # Fallback to default font
            font = ImageFont.load_default()
        
        # Draw "SC" text
        draw.text((18, 22), "SC", fill=(255, 255, 255, 255), font=font)
        
        return image
    
    def _load_icon_from_file(self) -> Optional[Image.Image]:
        """Try to load icon from icon.ico file"""
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.ico")
            if os.path.exists(icon_path):
                # Convert ICO to PNG for pystray
                with Image.open(icon_path) as img:
                    # Convert to RGBA and resize to 64x64
                    img = img.convert('RGBA')
                    img = img.resize((64, 64), Image.Resampling.LANCZOS)
                    return img
        except Exception as e:
            log.debug(f"Failed to load icon from file: {e}")
        return None
    
    def _get_icon_image(self) -> Image.Image:
        """Get the icon image, trying file first, then creating a default one"""
        # Try to load from icon.ico file first
        icon_image = self._load_icon_from_file()
        if icon_image:
            return icon_image
        
        # Fallback to created icon
        return self._create_icon_image()
    
    def _add_orange_dot(self, base_image: Image.Image) -> Image.Image:
        """Add an orange dot to the icon to indicate downloading"""
        # Create a copy to avoid modifying the original
        image = base_image.copy()
        draw = ImageDraw.Draw(image)
        
        # Draw orange dot in bottom-right corner
        dot_size = 20
        x = image.width - dot_size - 4
        y = image.height - dot_size - 4
        
        # Draw the dot with a border for better visibility
        draw.ellipse([x, y, x + dot_size, y + dot_size], 
                    fill=(255, 140, 0, 255),  # Orange
                    outline=(200, 100, 0, 255),  # Darker orange border
                    width=2)
        
        return image
    
    def _on_quit(self, icon, item):
        """Handle quit menu item click"""
        log.info("Quit requested from system tray")
        try:
            if self.quit_callback:
                self.quit_callback()
            else:
                # Default behavior - set stop event
                self._stop_event.set()
        except SystemExit:
            # Handle sys.exit() calls gracefully
            log.info("System exit requested from quit callback")
            self._stop_event.set()
        except Exception as e:
            log.error(f"Error in quit callback: {e}")
            self._stop_event.set()
        finally:
            icon.stop()
    
    def _on_icon_click(self, icon, item):
        """Handle left click on tray icon - do nothing"""
        # Left click does nothing, only right click shows menu
        pass
    
    def _create_menu(self) -> pystray.Menu:
        """Create the context menu for the tray icon"""
        return pystray.Menu(
            pystray.MenuItem("SkinCloner", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit)
        )
    
    def _run_tray(self):
        """Run the tray icon in a separate thread"""
        try:
            # Store base icon for later use
            self._base_icon_image = self._get_icon_image()
            icon_image = self._base_icon_image
            menu = self._create_menu()
            
            self.icon = pystray.Icon(
                "SkinCloner",
                icon_image,
                "SkinCloner",
                menu,
                default_action=self._on_icon_click
            )
            
            log.info("System tray icon started")
            # Use run_detached to prevent blocking the main thread
            self.icon.run_detached()
        except Exception as e:
            log.error(f"Failed to start system tray: {e}")
    
    def start(self):
        """Start the system tray icon"""
        if self.tray_thread and self.tray_thread.is_alive():
            log.warning("System tray is already running")
            return
        
        try:
            self.tray_thread = threading.Thread(target=self._run_tray, daemon=True)
            self.tray_thread.start()
            log.info("System tray manager started - no console window")
        except Exception as e:
            log.error(f"Failed to start system tray manager: {e}")
    
    def stop(self):
        """Stop the system tray icon"""
        if self.icon:
            try:
                self.icon.stop()
                log.info("System tray icon stopped")
            except Exception as e:
                log.error(f"Failed to stop system tray icon: {e}")
        
        if self.tray_thread and self.tray_thread.is_alive():
            self.tray_thread.join(timeout=2.0)
    
    def is_running(self) -> bool:
        """Check if the tray icon is running"""
        return self.icon is not None and self.tray_thread is not None and self.tray_thread.is_alive()
    
    def wait_for_quit(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for quit signal from tray
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if quit was requested, False if timeout
        """
        return self._stop_event.wait(timeout)
    
    def set_downloading(self, is_downloading: bool):
        """
        Update the tray icon to show downloading status
        
        Args:
            is_downloading: True to show orange dot, False to show normal icon
        """
        # Wait for tray icon to be ready (up to 5 seconds)
        max_wait = 5.0
        wait_interval = 0.1
        elapsed = 0.0
        
        while (not self.icon or not self._base_icon_image) and elapsed < max_wait:
            threading.Event().wait(wait_interval)
            elapsed += wait_interval
        
        if not self.icon or not self._base_icon_image:
            log.warning(f"Tray icon not ready, cannot set downloading status to {is_downloading}")
            return
        
        try:
            self._is_downloading = is_downloading
            
            if is_downloading:
                # Show icon with orange dot
                new_icon = self._add_orange_dot(self._base_icon_image)
                self.icon.icon = new_icon
                log.info("Orange icon on")
            else:
                # Show normal icon
                self.icon.icon = self._base_icon_image
                log.info("Orange icon off")
        except Exception as e:
            log.error(f"Failed to update tray icon: {e}")
