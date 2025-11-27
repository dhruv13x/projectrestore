# projectrestore/tests/test_init.py

import pytest

def test_projectrestore_import():
    """
    Test that the projectrestore package can be imported without errors.
    This is primarily for coverage of the __init__.py file.
    """
    try:
        import projectrestore
    except ImportError as e:
        pytest.fail(f"Failed to import projectrestore package: {e}")
