#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Path Cache
Caches skin and chroma file paths for O(1) lookup instead of filesystem scanning.
"""

import threading
from pathlib import Path
from typing import Dict, Optional, Set

from utils.core.logging import get_logger

log = get_logger()


class SkinPathCache:
    """Cache skin/chroma paths for fast lookup.
    
    Structure:
    - _skin_cache: Maps skin_id -> file path (for base skins)
    - _chroma_cache: Maps chroma_id -> file path (for chromas)
    - _champion_skins: Maps champion_id -> set of skin_ids (for quick champion lookup)
    
    Memory estimate: ~0.5-1 MB for 1500 skins + 5000 chromas
    """
    
    def __init__(self):
        self._skin_cache: Dict[int, Path] = {}
        self._chroma_cache: Dict[int, Path] = {}
        self._champion_skins: Dict[int, Set[int]] = {}
        self._lock = threading.Lock()
        self._built = False
    
    @property
    def is_built(self) -> bool:
        """Check if cache has been built."""
        return self._built
    
    def build(self, skins_dir: Path) -> None:
        """Scan skins directory and build the cache.
        
        Expected structure:
        skins_dir/
        ├── {champion_id}/
        │   ├── {skin_id}/
        │   │   ├── {skin_id}.zip or .fantome  (base skin)
        │   │   ├── {chroma_id}/
        │   │   │   └── {chroma_id}.zip or .fantome
        """
        with self._lock:
            if self._built:
                return
            
            self._skin_cache.clear()
            self._chroma_cache.clear()
            self._champion_skins.clear()
            
            if not skins_dir.exists():
                log.warning(f"[CACHE] Skins directory does not exist: {skins_dir}")
                self._built = True
                return
            
            skin_count = 0
            chroma_count = 0
            
            try:
                # Iterate through champion directories
                for champ_dir in skins_dir.iterdir():
                    if not champ_dir.is_dir():
                        continue
                    
                    try:
                        champion_id = int(champ_dir.name)
                    except ValueError:
                        continue  # Skip non-numeric directories
                    
                    self._champion_skins[champion_id] = set()
                    
                    # Iterate through skin directories
                    for skin_dir in champ_dir.iterdir():
                        if not skin_dir.is_dir():
                            continue
                        
                        try:
                            skin_id = int(skin_dir.name)
                        except ValueError:
                            continue
                        
                        self._champion_skins[champion_id].add(skin_id)
                        
                        # Look for base skin file
                        skin_zip = skin_dir / f"{skin_id}.zip"
                        skin_fantome = skin_dir / f"{skin_id}.fantome"
                        
                        if skin_zip.exists():
                            self._skin_cache[skin_id] = skin_zip
                            skin_count += 1
                        elif skin_fantome.exists():
                            self._skin_cache[skin_id] = skin_fantome
                            skin_count += 1
                        
                        # Look for chroma directories
                        for chroma_dir in skin_dir.iterdir():
                            if not chroma_dir.is_dir():
                                continue
                            
                            try:
                                chroma_id = int(chroma_dir.name)
                            except ValueError:
                                continue
                            
                            chroma_zip = chroma_dir / f"{chroma_id}.zip"
                            chroma_fantome = chroma_dir / f"{chroma_id}.fantome"
                            
                            if chroma_zip.exists():
                                self._chroma_cache[chroma_id] = chroma_zip
                                chroma_count += 1
                            elif chroma_fantome.exists():
                                self._chroma_cache[chroma_id] = chroma_fantome
                                chroma_count += 1
                
                self._built = True
                log.info(f"[CACHE] Built skin cache: {skin_count} skins, {chroma_count} chromas, {len(self._champion_skins)} champions")
                
            except Exception as e:
                log.error(f"[CACHE] Failed to build skin cache: {e}")
                self._built = True  # Mark as built to prevent retry loops
    
    def get_skin(self, skin_id: int) -> Optional[Path]:
        """Get cached path for a skin by ID."""
        return self._skin_cache.get(skin_id)
    
    def get_chroma(self, chroma_id: int) -> Optional[Path]:
        """Get cached path for a chroma by ID."""
        return self._chroma_cache.get(chroma_id)
    
    def get_skins_for_champion(self, champion_id: int) -> Set[int]:
        """Get all skin IDs for a champion."""
        return self._champion_skins.get(champion_id, set())
    
    def has_skin(self, skin_id: int) -> bool:
        """Check if a skin is in the cache."""
        return skin_id in self._skin_cache
    
    def has_chroma(self, chroma_id: int) -> bool:
        """Check if a chroma is in the cache."""
        return chroma_id in self._chroma_cache
    
    def invalidate(self) -> None:
        """Clear the cache (call when skins are added/removed)."""
        with self._lock:
            self._skin_cache.clear()
            self._chroma_cache.clear()
            self._champion_skins.clear()
            self._built = False
            log.debug("[CACHE] Skin cache invalidated")
    
    def refresh(self, skins_dir: Path) -> None:
        """Rebuild the cache."""
        self.invalidate()
        self.build(skins_dir)
    
    def stats(self) -> dict:
        """Get cache statistics."""
        return {
            "built": self._built,
            "skins": len(self._skin_cache),
            "chromas": len(self._chroma_cache),
            "champions": len(self._champion_skins),
        }
