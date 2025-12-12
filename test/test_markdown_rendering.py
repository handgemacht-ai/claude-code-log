#!/usr/bin/env python3
"""Test cases for server-side markdown rendering."""

import json
import tempfile
from pathlib import Path
from claude_code_log.converter import load_transcript
from claude_code_log.html.renderer import generate_html


def test_server_side_markdown_rendering():
    """Test that markdown is rendered server-side and marked.js is not included."""
    # Assistant message with markdown content
    assistant_message = {
        "type": "assistant",
        "timestamp": "2025-06-11T22:44:17.436Z",
        "parentUuid": None,
        "isSidechain": False,
        "userType": "assistant",
        "cwd": "/tmp",
        "sessionId": "test_session",
        "version": "1.0.0",
        "uuid": "test_md_001",
        "requestId": "req_001",
        "message": {
            "id": "msg_001",
            "type": "message",
            "role": "assistant",
            "model": "claude-3-5-sonnet-20241022",
            "content": [
                {
                    "type": "text",
                    "text": "# Test Markdown\n\nThis is **bold** text and `code` inline.",
                }
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(assistant_message) + "\n")
        f.flush()
        test_file_path = Path(f.name)

    try:
        messages = load_transcript(test_file_path)
        html = generate_html(messages, "Test Transcript")

        # Should NOT include marked.js script references
        assert "marked" not in html, "Should not include marked.js reference"
        assert "import { marked }" not in html, "Should not import marked module"
        assert "marked.parse" not in html, "Should not use marked.parse function"
        assert "DOMContentLoaded" not in html or "marked" not in html, (
            "Should not have markdown-related DOM handlers"
        )

        # Should include rendered HTML from markdown
        assert "<h1>Test Markdown</h1>" in html, (
            "Should render markdown heading as HTML"
        )
        assert "<strong>bold</strong>" in html, "Should render bold text as HTML"
        assert "<code>code</code>" in html, "Should render inline code as HTML"

        print("✓ Test passed: Markdown is rendered server-side")

    finally:
        test_file_path.unlink()


def test_user_message_not_markdown_rendered():
    """Test that user messages are not markdown rendered (shown as-is in pre tags)."""
    user_message = {
        "type": "user",
        "timestamp": "2025-06-11T22:44:17.436Z",
        "parentUuid": None,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": "test_session",
        "version": "1.0.0",
        "uuid": "test_md_002",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "# This should NOT be rendered\n\n**This should stay bold**",
                }
            ],
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(user_message) + "\n")
        f.flush()
        test_file_path = Path(f.name)

    try:
        messages = load_transcript(test_file_path)
        html = generate_html(messages, "Test Transcript")

        # User messages should be shown as-is in pre tags, not rendered as HTML
        assert "<pre># This should NOT be rendered" in html, (
            "User markdown should remain as text in pre tags"
        )
        assert "**This should stay bold**</pre>" in html, (
            "User markdown asterisks should remain literal"
        )
        assert "<h1>This should NOT be rendered</h1>" not in html, (
            "User markdown should not be rendered as HTML"
        )
        assert "<strong>This should stay bold</strong>" not in html, (
            "User markdown should not be rendered as HTML"
        )

        print("✓ Test passed: User messages are not markdown rendered")

    finally:
        test_file_path.unlink()


if __name__ == "__main__":
    test_server_side_markdown_rendering()
    test_user_message_not_markdown_rendered()
    print("\n✅ All markdown rendering tests passed!")
