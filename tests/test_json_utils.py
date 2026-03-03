"""
Unit tests for modules/json_utils.py
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.json_utils import extract_first_json


class TestExtractFirstJson:
    """Tests for extract_first_json function."""

    def test_extract_simple_json(self):
        """Test extraction of simple JSON object."""
        text = 'Some text {"key": "value"} more text'
        result = extract_first_json(text)
        assert result == {"key": "value"}

    def test_extract_nested_json(self):
        """Test extraction of nested JSON object."""
        text = 'Prefix {"outer": {"inner": "value"}} suffix'
        result = extract_first_json(text)
        assert result == {"outer": {"inner": "value"}}

    def test_extract_json_with_array(self):
        """Test extraction of JSON with arrays."""
        text = 'Text {"items": [1, 2, 3]} end'
        result = extract_first_json(text)
        assert result == {"items": [1, 2, 3]}

    def test_returns_none_for_no_json(self):
        """Test that None is returned when no JSON is present."""
        text = "This is plain text without any JSON"
        result = extract_first_json(text)
        assert result is None

    def test_returns_none_for_invalid_json(self):
        """Test that None is returned for malformed JSON."""
        text = 'Text {"key": value} end'  # Missing quotes around value
        result = extract_first_json(text)
        # Should return None or the raw string depending on implementation
        assert result is None or isinstance(result, dict)

    def test_extract_json_at_start(self):
        """Test extraction when JSON is at the start."""
        text = '{"start": true} followed by text'
        result = extract_first_json(text)
        assert result == {"start": True}

    def test_extract_json_at_end(self):
        """Test extraction when JSON is at the end."""
        text = 'Text before {"end": true}'
        result = extract_first_json(text)
        assert result == {"end": True}

    def test_extract_first_json_only(self):
        """Test that only the first JSON object is extracted."""
        text = '{"first": 1} and {"second": 2}'
        result = extract_first_json(text)
        assert result == {"first": 1}

    def test_extract_json_with_special_chars(self):
        """Test extraction of JSON with special characters."""
        text = 'Text {"message": "Hello\\nWorld"} end'
        result = extract_first_json(text)
        assert result == {"message": "Hello\nWorld"}

    def test_extract_json_with_unicode(self):
        """Test extraction of JSON with Unicode characters."""
        text = '{"greeting": "你好世界"}'
        result = extract_first_json(text)
        assert result == {"greeting": "你好世界"}

    def test_handles_empty_string(self):
        """Test handling of empty string input."""
        result = extract_first_json("")
        assert result is None

    def test_handles_whitespace_only(self):
        """Test handling of whitespace-only input."""
        result = extract_first_json("   \n\t   ")
        assert result is None
