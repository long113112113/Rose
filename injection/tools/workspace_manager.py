
import os
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

class WorkspaceManager:
    def __init__(self, workspace_root: str = "d:/Rose/workspace"):
        self.workspace_root = Path(workspace_root)
        self.tools_dir = Path(__file__).parent
        self.wad_extract_exe = self.tools_dir / "wad-extract.exe"
        self.ritobin_exe = self.tools_dir / "ritobin-tools.exe"
        self.overlay_dir = self.tools_dir.parent / "overlay"

    def get_overlay_wad(self) -> Optional[Path]:
        """Checks for wad.client in the overlay or debug directory."""
        # Check debug directory first
        debug_dir = Path("d:/Rose/overlay_debug")
        if debug_dir.exists():
            wads = list(debug_dir.glob("*.wad.client"))
            if wads:
                return wads[0]
        
        # Check standard overlay directory
        wad_path = self.overlay_dir / "wad.client"
        if wad_path.exists():
            return wad_path
        return None

    def extract_and_setup(self, wad_path: Path, champion: str, skin_id: str) -> Tuple[bool, str]:
        """
        Extracts the WAD to workspace/{champion}/{skin_id}, moving files to 'extracted'.
        """
        if not wad_path.exists():
            return False, f"WAD file not found: {wad_path}"

        # 1. Extract to temp directory first
        temp_dir = self.workspace_root / "temp_import"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        print(f"[Workspace] Extracting {wad_path} to {temp_dir}...")
        
        try:
            process = subprocess.run(
                [str(self.wad_extract_exe), str(wad_path), str(temp_dir)],
                capture_output=True,
                text=True
            )
            
            if process.returncode != 0:
                return False, f"Extraction failed (Exit Code {process.returncode}): {process.stderr}"
                
        except Exception as e:
            return False, f"Extraction execution error: {e}"

        # 2. Setup destination
        dest_dir = self.workspace_root / champion / skin_id
        extracted_dir = dest_dir / "extracted"
        dist_dir = dest_dir / "dist"
        
        if extracted_dir.exists():
            print(f"[Workspace] Cleaning previous extracted data in {extracted_dir}...")
            shutil.rmtree(extracted_dir)
        
        extracted_dir.parent.mkdir(parents=True, exist_ok=True)
        dist_dir.mkdir(exist_ok=True)
        
        print(f"[Workspace] Moving files to {extracted_dir}...")
        try:
             # Retry loop for Windows file locking could be added here if needed
             shutil.move(str(temp_dir), str(extracted_dir))
        except Exception as e:
             return False, f"Failed to move extracted files: {e}"

        # 3. Save source info
        info = {
            "original_path": str(wad_path),
            "champion": champion,
            "skin_id": skin_id,
            "import_time": time.time()
        }
        with open(dest_dir / "source_info.json", "w") as f:
            json.dump(info, f, indent=4)

        # 4. Convert bins
        print("[Workspace] Converting .bin files to .py...")
        self.convert_bins(extracted_dir)

        return True, f"Successfully imported to {dest_dir}"

    def ensure_hashes(self):
        """
        Ensures that the hash file exists. If not, attempts to download it.
        Checks default location: Documents/LeagueToolkit/bin_hashtables/hashes.bin
        """
        docs_dir = Path(os.path.expanduser("~")) / "Documents"
        hashes_path = docs_dir / "LeagueToolkit" / "bin_hashtables" / "hashes.bin"
        
        if not hashes_path.exists():
            print("[Workspace] Hash file not found. Downloading via ritobin-tools...")
            try:
                subprocess.run([str(self.ritobin_exe), "download-hashes"], check=True, capture_output=False)
                print("[Workspace] Hashes downloaded successfully.")
            except Exception as e:
                print(f"[Workspace] Failed to download hashes: {e}")
        else:
            print(f"[Workspace] Hashes found at {hashes_path}")

    def inject_resource_map(self, file_path: Path):
        """
        Injects content from resource_map_entry.txt into resourceMap of the given file.
        Uses brace counting to correctly identify the closing brace of resourceMap.
        """
        resource_file = Path("d:/Rose/injection/resource/resource_map_entry.txt")
        if not resource_file.exists():
            return

        try:
            with open(resource_file, "r") as f:
                injection_content = f.read().strip()
            
            if not injection_content:
                return

            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []
            inside_resource_map = False
            resource_map_indent = ""
            brace_depth = 0  # Track nested braces
            injected = False
            
            for line in lines:
                if not injected and "resourceMap: map[hash,link] = {" in line:
                    inside_resource_map = True
                    resource_map_indent = line.split("resourceMap")[0]
                    brace_depth = 1  # We just opened the resourceMap brace
                    new_lines.append(line)
                    continue
                
                if inside_resource_map:
                    # Count braces in this line
                    brace_depth += line.count("{")
                    brace_depth -= line.count("}")
                    
                    # When depth reaches 0, we've found the closing brace of resourceMap
                    if brace_depth == 0:
                        # Inject BEFORE the closing brace line
                        injection_indent = resource_map_indent + "    "
                        # Ensure we don't inject if already present
                        if injection_content not in "".join(new_lines[-5:]): 
                             new_lines.append(f"{injection_indent}{injection_content}\n")
                        
                        inside_resource_map = False 
                        injected = True
                        new_lines.append(line)
                        continue
                
                new_lines.append(line)

            if injected:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                print(f"[Workspace] Injected resource map into {file_path.name}")

        except Exception as e:
            print(f"[Workspace] Failed to inject resource map into {file_path.name}: {e}")

    def inject_persistent_effects(self, file_path: Path):
        """
        Injects PersistentEffectConditions after mResourceResolver.
        - If PersistentEffectConditions block already exists: inject child element
        - If not present: inject full block
        Uses separate resource files for cleaner code.
        """
        child_file = Path("d:/Rose/injection/resource/persistent_effect_child.txt")
        full_file = Path("d:/Rose/injection/resource/persistent_effect_full.txt")
        
        if not child_file.exists() and not full_file.exists():
            return

        try:
            child_element = ""
            full_block = ""
            
            if child_file.exists():
                with open(child_file, "r") as f:
                    child_element = f.read()
            
            if full_file.exists():
                with open(full_file, "r") as f:
                    full_block = f.read()
            
            if not full_block.strip() and not child_element.strip():
                return

            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []
            injected = False
            i = 0
            
            while i < len(lines):
                line = lines[i]
                new_lines.append(line)
                
                # Look for mResourceResolver
                if not injected and "mResourceResolver:" in line:
                    # Check if next line has PersistentEffectConditions
                    if i + 1 < len(lines) and "PersistentEffectConditions: list2[pointer] = {" in lines[i + 1]:
                        # Block exists - need to inject child element inside it
                        i += 1
                        new_lines.append(lines[i])  # Add the PersistentEffectConditions line
                        
                        # Peek at next line to get indentation of existing entries
                        if i + 1 < len(lines):
                            # Check for duplicate - look for unique identifier in child_element
                            # Extract effectKey from child_element for duplicate check
                            file_content = "".join(lines)
                            if "effectKey: hash = 0xd31755a9" in file_content:
                                # Already injected, skip
                                injected = True
                                print(f"[Workspace] PersistentEffectConditionData already exists in {file_path.name}, skipping")
                            else:
                                entry_indent = lines[i + 1][:len(lines[i + 1]) - len(lines[i + 1].lstrip())]
                                # Inject our child element with same indentation
                                adjusted_child = self._adjust_indent(child_element, entry_indent)
                                new_lines.append(adjusted_child)
                                if not adjusted_child.endswith("\n"):
                                    new_lines.append("\n")
                                injected = True
                                print(f"[Workspace] Injected PersistentEffectConditionData into existing block in {file_path.name}")
                        # DON'T skip next line - let the loop continue normally
                    else:
                        # Block doesn't exist - inject full block after mResourceResolver
                        base_indent = line[:len(line) - len(line.lstrip())]
                        adjusted_block = self._adjust_indent(full_block, base_indent)
                        new_lines.append(adjusted_block)
                        if not adjusted_block.endswith("\n"):
                            new_lines.append("\n")
                        injected = True
                        print(f"[Workspace] Injected PersistentEffectConditions block into {file_path.name}")
                
                i += 1

            if injected:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)

        except Exception as e:
            print(f"[Workspace] Failed to inject persistent effects into {file_path.name}: {e}")

    def _adjust_indent(self, content: str, base_indent: str) -> str:
        """Adjusts indentation of content to match base_indent."""
        lines = content.split("\n")
        if not lines:
            return content
        
        # Find minimum indent in content (excluding empty lines)
        min_indent = float('inf')
        for line in lines:
            if line.strip():
                current_indent = len(line) - len(line.lstrip())
                min_indent = min(min_indent, current_indent)
        
        if min_indent == float('inf'):
            min_indent = 0
        
        # Adjust each line
        adjusted = []
        for line in lines:
            if line.strip():
                # Remove old indent, add new base indent
                stripped = line[min_indent:] if len(line) >= min_indent else line.lstrip()
                adjusted.append(base_indent + stripped)
            else:
                adjusted.append(line)
        
        return "\n".join(adjusted)


    def convert_bins(self, root: Path):
        """
        Recursively finds .bin files and runs ritobin-tools.exe on them.
        """
        self.ensure_hashes()
        
        bin_files = list(root.rglob("*.bin"))
        print(f"[Workspace] Found {len(bin_files)} .bin files to convert.")
        count = 0
        for path in bin_files:
             try:
                 # Use 'convert' subcommand
                 # ritobin-tools converts file.bin -> file.py by default
                 result = subprocess.run([str(self.ritobin_exe), "convert", str(path)], capture_output=True, text=True)
                 if result.returncode == 0:
                     count += 1
                     # Attempt injection on the generated .py file
                     py_file = path.with_suffix(".py")
                     if py_file.exists():
                         self.inject_resource_map(py_file)
                         self.inject_persistent_effects(py_file)
                 else:
                     print(f"[Workspace] Failed to convert {path.name}. Exit code: {result.returncode}. Stderr: {result.stderr}")
             except Exception as e:
                 print(f"[Workspace] Exception converting {path.name}: {e}")
        print(f"[Workspace] Converted {count} .bin files.")

    def clean_workspace(self, champion: str, skin_id: str):
         target = self.workspace_root / champion / skin_id / "extracted"
         if target.exists():
             shutil.rmtree(target)
             print(f"[Workspace] Cleaned up {target}")
         else:
             print(f"[Workspace] Nothing to clean at {target}")

if __name__ == "__main__":
    wm = WorkspaceManager()
    wad = wm.get_overlay_wad()
    if wad:
        print(f"Found overlay WAD: {wad}")
        # Manual test with explicit champion/skin
        success, msg = wm.extract_and_setup(wad, "Ahri", "Skin0_ManualTest")
        print(msg)
    else:
        print("No overlay WAD found (wad.client).")
