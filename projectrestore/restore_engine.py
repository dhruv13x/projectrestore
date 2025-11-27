# projectrestore/projectrestore/restore_engine.py

import os
import sys
import shutil
from src.common import manifest, cas

def restore_snapshot(manifest_path: str, destination_path: str, hooks: dict = None) -> None:
    """
    Restores a project snapshot from the vault to the destination path.
    """
    # Import hooks helper
    try:
        from src.common.hooks import run_hook
    except ImportError:
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
        from src.common.hooks import run_hook

    # --- Run Pre-Restore Hook ---
    if hooks and "pre_restore" in hooks:
        run_hook("pre_restore", hooks["pre_restore"])

    # --- Safety Checks (Zero Trust) ---
    abs_manifest_path = os.path.abspath(manifest_path)
    abs_destination_path = os.path.abspath(destination_path)
    vault_root = os.path.dirname(os.path.dirname(abs_manifest_path))
    
    try:
        if os.path.commonpath([vault_root, abs_destination_path]) == vault_root:
            raise ValueError("Destination path is inside the Vault.")
        if os.path.commonpath([vault_root, abs_destination_path]) == abs_destination_path:
            raise ValueError("Vault path is inside the Destination path.")
    except ValueError as e:
        if "Vault" in str(e): raise
        pass

    print(f"Loading manifest from: {manifest_path}")
    try:
        snapshot_data = manifest.load_manifest(manifest_path)
    except Exception as e:
        print(f"Failed to load manifest: {e}")
        sys.exit(1)

    # Detect Version
    version = snapshot_data.get("version", 1)
    print(f"Snapshot Version: {version}")

    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    objects_dir = os.path.abspath(os.path.join(manifest_dir, "../objects"))

    if not os.path.exists(objects_dir):
        print(f"Error: Objects directory not found at {objects_dir}")
        sys.exit(1)

    print(f"Restoring to: {destination_path}")
    os.makedirs(destination_path, exist_ok=True)

    files = snapshot_data.get("files", {})
    restored_count = 0
    skipped_count = 0

    for rel_path, entry in files.items():
        # Zero-Trust Validation
        if os.path.isabs(rel_path) or ".." in os.path.normpath(rel_path).split(os.sep):
            print(f"WARNING: Skipping unsafe path '{rel_path}'")
            skipped_count += 1
            continue

        # Handle Version 1 vs Version 2
        if isinstance(entry, str):
            # V1: entry is just the hash string
            file_hash = entry
            metadata = None
        else:
            # V2: entry is a dict
            file_hash = entry.get("hash")
            metadata = entry

        object_source = os.path.join(objects_dir, file_hash)
        file_dest = os.path.join(destination_path, rel_path)
        
        if not os.path.exists(object_source):
             print(f"ERROR: Missing object {file_hash} for file {rel_path}")
             skipped_count += 1
             continue

        try:
            # Use cas helper to handle compression/decompression
            cas.restore_object_to_file(object_source, file_dest)
            
            # Apply Metadata (V2)
            if metadata:
                try:
                    # Restore permissions
                    if "mode" in metadata:
                        os.chmod(file_dest, metadata["mode"])
                    
                    # Restore timestamps (atime, mtime)
                    # We use mtime for both since atime isn't stored
                    if "mtime" in metadata:
                        mtime = metadata["mtime"]
                        os.utime(file_dest, (mtime, mtime))
                        
                except Exception as e:
                    print(f"Warning: Failed to apply metadata for {rel_path}: {e}")

            print(f"Restoring: {rel_path}")
            restored_count += 1
            
        except Exception as e:
            print(f"Failed to restore {rel_path}: {e}")
            skipped_count += 1

    print(f"Restore complete. Restored: {restored_count}, Skipped/Failed: {skipped_count}")

    # --- Run Post-Restore Hook ---
    if hooks and "post_restore" in hooks:
        run_hook("post_restore", hooks["post_restore"])
