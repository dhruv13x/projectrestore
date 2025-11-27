# projectrestore/tests/test_restore_engine.py

import os
import json
import shutil
import pytest
from unittest.mock import patch, MagicMock
from projectrestore import restore_engine

@pytest.fixture
def vault_structure(tmp_path):
    """
    Creates a mock vault structure:
    tmp_path/
        vault/
            snapshots/
                manifest.json
            objects/
    """
    vault = tmp_path / "vault"
    snapshots = vault / "snapshots"
    objects = vault / "objects"

    snapshots.mkdir(parents=True)
    objects.mkdir(parents=True)

    return vault, snapshots, objects

def test_restore_happy_path(vault_structure, tmp_path):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    dest_path = tmp_path / "restore_dest"

    # Create a dummy object
    file_content = b"Hello World"
    file_hash = "hash123"
    (objects / file_hash).write_bytes(file_content)

    # Create manifest
    manifest_data = {
        "files": {
            "hello.txt": file_hash
        }
    }
    manifest_path.write_text(json.dumps(manifest_data))

    # Run restore
    restore_engine.restore_snapshot(str(manifest_path), str(dest_path))

    # Verify
    assert (dest_path / "hello.txt").exists()
    assert (dest_path / "hello.txt").read_bytes() == file_content

def test_restore_traversal_attack(vault_structure, tmp_path, capsys):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    dest_path = tmp_path / "restore_dest"

    manifest_data = {
        "files": {
            "../outside.txt": "hash123"
        }
    }
    manifest_path.write_text(json.dumps(manifest_data))

    restore_engine.restore_snapshot(str(manifest_path), str(dest_path))

    captured = capsys.readouterr()
    # Updated expectation: Unified error message
    assert "Skipping unsafe path" in captured.out
    assert not (dest_path.parent / "outside.txt").exists()

def test_restore_absolute_path_attack(vault_structure, tmp_path, capsys):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    dest_path = tmp_path / "restore_dest"

    abs_path = str(tmp_path / "abs_file.txt")
    manifest_data = {
        "files": {
            abs_path: "hash123"
        }
    }
    manifest_path.write_text(json.dumps(manifest_data))

    restore_engine.restore_snapshot(str(manifest_path), str(dest_path))

    captured = capsys.readouterr()
    # Updated expectation: Unified error message
    assert "Skipping unsafe path" in captured.out
    assert not (tmp_path / "abs_file.txt").exists()

def test_restore_anti_inception_dest_in_vault(vault_structure):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    # Destination inside vault
    dest_path = vault / "restored"

    with pytest.raises(ValueError, match="Destination path is inside the Vault"):
        restore_engine.restore_snapshot(str(manifest_path), str(dest_path))

def test_restore_anti_inception_vault_in_dest(vault_structure, tmp_path):
    # Setup vault inside dest
    dest_path = tmp_path / "outer_dest"
    vault = dest_path / "vault"
    snapshots = vault / "snapshots"
    objects = vault / "objects"
    snapshots.mkdir(parents=True)
    objects.mkdir(parents=True)

    manifest_path = snapshots / "manifest.json"

    with pytest.raises(ValueError, match="Vault path is inside the Destination path"):
        restore_engine.restore_snapshot(str(manifest_path), str(dest_path))

def test_restore_missing_object(vault_structure, tmp_path, capsys):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    dest_path = tmp_path / "restore_dest"

    # Missing object
    manifest_data = {
        "files": {
            "missing.txt": "missing_hash"
        }
    }
    manifest_path.write_text(json.dumps(manifest_data))

    restore_engine.restore_snapshot(str(manifest_path), str(dest_path))

    captured = capsys.readouterr()
    assert "ERROR: Missing object missing_hash" in captured.out
    assert not (dest_path / "missing.txt").exists()

def test_restore_corrupted_manifest(vault_structure, tmp_path):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    dest_path = tmp_path / "restore_dest"

    manifest_path.write_text("{ invalid json")

    with pytest.raises(SystemExit) as e:
        restore_engine.restore_snapshot(str(manifest_path), str(dest_path))
    assert e.value.code == 1

def test_objects_dir_missing(vault_structure, tmp_path, capsys):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    dest_path = tmp_path / "restore_dest"

    manifest_path.write_text("{}")

    # Remove objects dir
    shutil.rmtree(objects)

    with pytest.raises(SystemExit) as e:
        restore_engine.restore_snapshot(str(manifest_path), str(dest_path))
    assert e.value.code == 1

    captured = capsys.readouterr()
    assert "Objects directory not found" in captured.out

def test_restore_file_write_failure(vault_structure, tmp_path, capsys):
    vault, snapshots, objects = vault_structure
    manifest_path = snapshots / "manifest.json"
    dest_path = tmp_path / "restore_dest"

    file_content = b"content"
    file_hash = "hash123"
    (objects / file_hash).write_bytes(file_content)

    manifest_data = {
        "files": {
            "file.txt": file_hash
        }
    }
    manifest_path.write_text(json.dumps(manifest_data))

    # Mock shutil.copy2 to raise exception
    with patch("shutil.copy2", side_effect=OSError("Write failed")):
        restore_engine.restore_snapshot(str(manifest_path), str(dest_path))

    captured = capsys.readouterr()
    assert "Failed to restore file.txt" in captured.out
