#!/usr/bin/env python3
"""Unit tests for template utility functions and edge cases."""

import pytest
from datetime import datetime
from claude_code_log.parser import parse_timestamp, extract_text_content
from claude_code_log.renderer import extract_command_info
from claude_code_log.html_renderer import escape_html
from claude_code_log.utils import format_timestamp
from claude_code_log.models import TextContent, ToolUseContent, ToolResultContent


class TestTimestampHandling:
    """Test timestamp formatting and parsing functions."""

    def test_format_timestamp_valid_iso(self):
        """Test formatting valid ISO timestamps."""
        timestamp = "2025-06-14T10:30:45.123Z"
        result = format_timestamp(timestamp)
        assert result == "2025-06-14 10:30:45"

    def test_format_timestamp_without_milliseconds(self):
        """Test formatting ISO timestamps without milliseconds."""
        timestamp = "2025-06-14T10:30:45Z"
        result = format_timestamp(timestamp)
        assert result == "2025-06-14 10:30:45"

    def test_format_timestamp_invalid(self):
        """Test formatting invalid timestamps returns original."""
        invalid_timestamp = "not-a-timestamp"
        result = format_timestamp(invalid_timestamp)
        assert result == invalid_timestamp

    def test_parse_timestamp_valid(self):
        """Test parsing valid ISO timestamps."""
        timestamp = "2025-06-14T10:30:45.123Z"
        result = parse_timestamp(timestamp)
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 14

    def test_parse_timestamp_invalid(self):
        """Test parsing invalid timestamps returns None."""
        invalid_timestamp = "not-a-timestamp"
        result = parse_timestamp(invalid_timestamp)
        assert result is None


class TestContentExtraction:
    """Test content extraction and text processing functions."""

    def test_extract_text_content_from_list(self):
        """Test extracting text content from ContentItem list."""
        content_items = [
            TextContent(type="text", text="First part"),
            TextContent(type="text", text="Second part"),
        ]
        result = extract_text_content(content_items)
        assert result == "First part\nSecond part"

    def test_extract_text_content_from_mixed_list(self):
        """Test extracting text content from mixed ContentItem list."""
        content_items = [
            TextContent(type="text", text="Text content"),
            ToolUseContent(type="tool_use", id="tool_1", name="TestTool", input={}),
            TextContent(type="text", text="More text"),
        ]
        result = extract_text_content(content_items)
        assert result == "Text content\nMore text"

    def test_extract_text_content_from_string(self):
        """Test extracting text content from string."""
        content = "Simple string content"
        result = extract_text_content(content)
        assert result == "Simple string content"

    def test_extract_text_content_empty_list(self):
        """Test extracting text content from empty list."""
        content_items = []
        result = extract_text_content(content_items)
        assert result == ""

    def test_extract_text_content_no_text_items(self):
        """Test extracting text content from list with no text items."""
        content_items = [
            ToolUseContent(type="tool_use", id="tool_1", name="TestTool", input={}),
            ToolResultContent(
                type="tool_result", tool_use_id="tool_1", content="result"
            ),
        ]
        result = extract_text_content(content_items)
        assert result == ""


class TestCommandExtraction:
    """Test command information extraction from system messages."""

    def test_extract_command_info_complete(self):
        """Test extracting complete command information."""
        text = '<command-message>Testing...</command-message>\n<command-name>test-cmd</command-name>\n<command-args>--verbose</command-args>\n<command-contents>{"type": "text", "text": "Test content"}</command-contents>'

        command_name, command_args, command_contents = extract_command_info(text)

        assert command_name == "test-cmd"
        assert command_args == "--verbose"
        assert command_contents == "Test content"

    def test_extract_command_info_missing_parts(self):
        """Test extracting command info with missing parts."""
        text = "<command-name>minimal-cmd</command-name>"

        command_name, command_args, command_contents = extract_command_info(text)

        assert command_name == "minimal-cmd"
        assert command_args == ""
        assert command_contents == ""

    def test_extract_command_info_no_command(self):
        """Test extracting command info from non-command text."""
        text = "This is just regular text with no command tags"

        command_name, command_args, command_contents = extract_command_info(text)

        assert command_name == "system"
        assert command_args == ""
        assert command_contents == ""

    def test_extract_command_info_malformed_json(self):
        """Test extracting command contents with malformed JSON."""
        text = '<command-name>bad-json</command-name>\n<command-contents>{"invalid": json</command-contents>'

        command_name, command_args, command_contents = extract_command_info(text)

        assert command_name == "bad-json"
        assert (
            command_contents == '{"invalid": json'
        )  # Raw text when JSON parsing fails


class TestHtmlEscaping:
    """Test HTML escaping functionality."""

    def test_escape_html_basic(self):
        """Test escaping basic HTML characters."""
        text = '<script>alert("xss")</script>'
        result = escape_html(text)
        assert result == "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"

    def test_escape_html_ampersand(self):
        """Test escaping ampersands."""
        text = "Tom & Jerry"
        result = escape_html(text)
        assert result == "Tom &amp; Jerry"

    def test_escape_html_empty_string(self):
        """Test escaping empty string."""
        text = ""
        result = escape_html(text)
        assert result == ""

    def test_escape_html_already_escaped(self):
        """Test escaping already escaped content."""
        text = "&lt;div&gt;"
        result = escape_html(text)
        assert result == "&amp;lt;div&amp;gt;"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_format_timestamp_none(self):
        """Test formatting None timestamp."""
        result = format_timestamp(None)
        assert result == ""  # The function returns empty string for None input

    def test_extract_text_content_none(self):
        """Test extracting text content from None."""
        result = extract_text_content(None)
        assert result == ""

    def test_extract_command_info_empty_string(self):
        """Test extracting command info from empty string."""
        command_name, command_args, command_contents = extract_command_info("")

        assert command_name == "system"
        assert command_args == ""
        assert command_contents == ""

    def test_escape_html_unicode(self):
        """Test escaping Unicode characters."""
        text = "Café & naïve résumé 中文"
        result = escape_html(text)
        # Unicode should be preserved, only HTML chars escaped
        assert "Café" in result
        assert "&amp;" in result
        assert "中文" in result


if __name__ == "__main__":
    pytest.main([__file__])
