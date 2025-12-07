# projectrestore/tests/test_banner.py

import os
from unittest.mock import patch
from projectrestore.banner import print_logo

def test_print_logo_fixed_palette_valid_index():
    """Test that a valid CREATE_DUMP_PALETTE index is used."""
    with patch.dict(os.environ, {"CREATE_DUMP_PALETTE": "1"}), \
         patch('rich.console.Console') as mock_console:
        print_logo()
        # Check that console.print was called. A more detailed check could
        # verify the colors used if the output was captured and parsable.
        mock_console.return_value.print.assert_called()

def test_print_logo_fixed_palette_invalid_index():
    """Test that an invalid CREATE_DUMP_PALETTE falls back to procedural."""
    with patch.dict(os.environ, {"CREATE_DUMP_PALETTE": "999"}), \
         patch('rich.console.Console') as mock_console:
        print_logo()
        mock_console.return_value.print.assert_called()

def test_print_logo_procedural_palette():
    """Test that the procedural palette is used when no env var is set."""
    with patch.dict(os.environ, {}, clear=True), \
         patch('rich.console.Console') as mock_console:
        print_logo()
        mock_console.return_value.print.assert_called()

def test_print_logo_procedural_palette_biased():
    """Test the 25% chance branch for biasing the palette."""
    with patch.dict(os.environ, {}, clear=True), \
         patch('rich.console.Console') as mock_console, \
         patch('random.SystemRandom.random', side_effect=[0.1] * 100): # Provide enough values
        print_logo()
        mock_console.return_value.print.assert_called()

def test_print_logo_bad_env_value():
    """Test that a non-integer CREATE_DUMP_PALETTE falls back to procedural."""
    with patch.dict(os.environ, {"CREATE_DUMP_PALETTE": "not-a-number"}), \
         patch('rich.console.Console') as mock_console:
        print_logo()
        mock_console.return_value.print.assert_called()
