#!/usr/bin/env python3
"""Phase 8: Tests for message variants - slash commands, queue operations, and css_class modifiers.

These tests cover:
1. isMeta=True (slash command expanded prompts)
2. Queue-operation 'remove' rendering as steering messages
3. Multiple css_class modifiers (sidechain + error, etc.)
"""

import json
import tempfile
from pathlib import Path

from claude_code_log.converter import deduplicate_messages
from claude_code_log.converter import load_transcript
from claude_code_log.html.renderer import generate_html


class TestSlashCommandRendering:
    """Tests for isMeta=True slash command expanded prompts."""

    def test_slash_command_css_class(self):
        """Test that isMeta=True user messages get 'slash-command' CSS class."""
        # Parent user message (normal)
        parent_message = {
            "type": "user",
            "timestamp": "2025-06-11T22:45:17.436Z",
            "parentUuid": None,
            "isSidechain": False,
            "isMeta": False,
            "userType": "human",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "parent_001",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "/review"}],
            },
        }

        # Expanded slash command prompt (isMeta=True)
        slash_command_message = {
            "type": "user",
            "timestamp": "2025-06-11T22:45:17.436Z",  # Same timestamp as parent
            "parentUuid": "parent_001",
            "isSidechain": False,
            "isMeta": True,  # This is the key flag
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "slash_001",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "# Code Review Instructions\n\nPlease review the code...",
                    }
                ],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(parent_message) + "\n")
            f.write(json.dumps(slash_command_message) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            assert len(messages) == 2

            html = generate_html(messages, "Test Slash Command")

            # Check for slash-command CSS class
            assert "user slash-command" in html, (
                "isMeta=True should produce 'user slash-command' CSS class"
            )

            # Check for message title
            assert "User (slash command)" in html, (
                "isMeta=True should have 'User (slash command)' title"
            )

            # Check that markdown content is rendered
            assert "Code Review Instructions" in html, (
                "Slash command content should be rendered"
            )

        finally:
            test_file_path.unlink()

    def test_slash_command_sidechain(self):
        """Test slash command in sidechain context."""
        slash_command_sidechain = {
            "type": "user",
            "timestamp": "2025-06-11T22:45:17.436Z",
            "parentUuid": None,
            "isSidechain": True,  # Sidechain context
            "isMeta": True,  # Slash command
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "sidechain_slash_001",
            "agentId": "agent_001",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "# Sub-agent Slash Command\n\nInstructions for sub-agent...",
                    }
                ],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(slash_command_sidechain) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            html = generate_html(messages, "Test Sidechain Slash Command")

            # Sidechain user messages without tool results are skipped during filtering
            # (see _filter_messages in renderer.py). Even with isMeta=True, they don't
            # contain tool results so they are not rendered.
            assert "Sub-agent Slash Command" not in html, (
                "Sidechain user messages without tool results should be skipped"
            )

        finally:
            test_file_path.unlink()


class TestQueueOperationRemove:
    """Tests for queue-operation 'remove' rendering as steering messages."""

    def test_queue_operation_remove_rendered(self):
        """Test that queue-operation 'remove' is rendered as user steering message."""
        remove_message = {
            "type": "queue-operation",
            "operation": "remove",
            "timestamp": "2025-11-08T15:16:08.703Z",
            "content": [
                {
                    "type": "text",
                    "text": "User cancelled the queued operation",
                }
            ],
            "sessionId": "test_session",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(remove_message) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            assert len(messages) == 1

            html = generate_html(messages, "Test Queue Remove")

            # 'remove' operations should be rendered as steering messages
            assert "steering" in html, (
                "queue-operation 'remove' should have 'steering' CSS class"
            )

            # Check for message title
            assert "User (steering)" in html, (
                "queue-operation 'remove' should have 'User (steering)' title"
            )

            # Content should be visible
            assert "User cancelled the queued operation" in html, (
                "Remove message content should be rendered"
            )

        finally:
            test_file_path.unlink()

    def test_queue_operation_enqueue_not_rendered(self):
        """Test that queue-operation 'enqueue' is NOT rendered."""
        enqueue_message = {
            "type": "queue-operation",
            "operation": "enqueue",
            "timestamp": "2025-11-08T15:16:08.703Z",
            "content": [
                {
                    "type": "text",
                    "text": "This should not appear",
                }
            ],
            "sessionId": "test_session",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(enqueue_message) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            html = generate_html(messages, "Test Queue Enqueue")

            # 'enqueue' should NOT be rendered
            assert "This should not appear" not in html, (
                "queue-operation 'enqueue' should not be rendered"
            )

        finally:
            test_file_path.unlink()

    def test_queue_operation_dequeue_not_rendered(self):
        """Test that queue-operation 'dequeue' is NOT rendered as a message."""
        dequeue_message = {
            "type": "queue-operation",
            "operation": "dequeue",
            "timestamp": "2025-11-08T15:16:08.703Z",
            "sessionId": "test_session",
        }

        # Add a user message to have something in the transcript
        user_message = {
            "type": "user",
            "timestamp": "2025-11-08T15:16:08.800Z",
            "parentUuid": None,
            "isSidechain": False,
            "userType": "human",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "user_001",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Regular user message"}],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(dequeue_message) + "\n")
            f.write(json.dumps(user_message) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            html = generate_html(messages, "Test Queue Dequeue")

            # 'dequeue' should NOT create a visible message element
            # Check that no message has the queue-operation type in its CSS class
            assert 'class="message queue-operation' not in html.lower(), (
                "queue-operation 'dequeue' should not create a message element"
            )

            # The regular user message should be rendered
            assert "Regular user message" in html, "User message should be rendered"

        finally:
            test_file_path.unlink()


class TestCssClassModifiers:
    """Tests for CSS class composition with multiple modifiers."""

    def test_tool_result_error_sidechain(self):
        """Test tool_result with both error and sidechain modifiers."""
        # Need a tool_use first for pairing
        tool_use = {
            "type": "assistant",
            "timestamp": "2025-06-11T22:45:17.000Z",
            "parentUuid": None,
            "isSidechain": True,
            "agentId": "agent_001",
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "assistant_001",
            "message": {
                "id": "msg_001",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-20250514",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_001",
                        "name": "Read",
                        "input": {"file_path": "/nonexistent/file.txt"},
                    }
                ],
            },
        }

        tool_result_error = {
            "type": "user",
            "timestamp": "2025-06-11T22:45:18.000Z",
            "parentUuid": "assistant_001",
            "isSidechain": True,  # Sidechain
            "agentId": "agent_001",
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "user_001",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_001",
                        "content": "Error: File not found",
                        "is_error": True,  # Error flag
                    }
                ],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(tool_use) + "\n")
            f.write(json.dumps(tool_result_error) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            html = generate_html(messages, "Test Error Sidechain")

            # Check for combined CSS classes
            assert "tool_result" in html, "Should have tool_result base class"
            assert "error" in html, "Should have error modifier"
            assert "sidechain" in html, "Should have sidechain modifier"

            # Verify error content is visible
            assert "File not found" in html, "Error content should be rendered"

        finally:
            test_file_path.unlink()

    def test_user_compacted_sidechain(self):
        """Test user message with compacted and sidechain modifiers."""
        # Compacted messages have specific structure
        compacted_message = {
            "type": "user",
            "timestamp": "2025-06-11T22:45:17.436Z",
            "parentUuid": None,
            "isSidechain": True,
            "agentId": "agent_001",
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "compacted_001",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "<context-messages>\n[Compacted conversation]\n</context-messages>",
                    }
                ],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(compacted_message) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            html = generate_html(messages, "Test Compacted Sidechain")

            # Sidechain user messages are skipped (duplicate of Task prompt input)
            # Verify the raw content is not rendered
            assert "context-messages" not in html, (
                "Sidechain user messages should be skipped"
            )
            assert "[Compacted conversation]" not in html, (
                "Sidechain user message content should not be rendered"
            )

        finally:
            test_file_path.unlink()

    def test_system_info_with_sidechain(self):
        """Test system info message (though system messages don't have sidechain)."""
        system_info = {
            "type": "system",
            "timestamp": "2025-06-11T22:45:17.436Z",
            "parentUuid": None,
            "isSidechain": False,
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "system_001",
            "content": "Claude Code v1.0.0 initialized",
            "level": "info",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(system_info) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            html = generate_html(messages, "Test System Info")

            # Check for system-info CSS class
            assert "system-info" in html, "Should have system-info CSS class"

            # Content should be visible
            assert "Claude Code v1.0.0 initialized" in html, (
                "System info content should be rendered"
            )

        finally:
            test_file_path.unlink()


class TestDeduplicationWithModifiers:
    """Tests for deduplication handling with different message modifiers."""

    def test_slash_command_deduplication(self):
        """Test that slash command messages with same timestamp are properly deduplicated.

        Deduplication key is (type, timestamp, is_meta, session_id, content_key).
        For user messages without tool_result, content_key falls back to uuid.
        So messages with same uuid (or same tool_use_id) are deduplicated.
        """
        # Two messages with same timestamp and same uuid - should be deduplicated
        message1 = {
            "type": "user",
            "timestamp": "2025-06-11T22:45:17.436Z",
            "parentUuid": None,
            "isSidechain": False,
            "isMeta": True,
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",
            "version": "1.0.0",
            "uuid": "msg_001",  # Same UUID = same content_key = will be deduplicated
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Slash command content"}],
            },
        }

        # Duplicate message (same timestamp, isMeta, sessionId, and same uuid for dedup)
        message2 = {
            "type": "user",
            "timestamp": "2025-06-11T22:45:17.436Z",  # Same timestamp
            "parentUuid": None,
            "isSidechain": False,
            "isMeta": True,  # Same isMeta
            "userType": "external",
            "cwd": "/tmp",
            "sessionId": "test_session",  # Same session
            "version": "1.0.0",
            "uuid": "msg_001",  # Same UUID = deduplication will occur
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Slash command content"}],
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(message1) + "\n")
            f.write(json.dumps(message2) + "\n")
            f.flush()
            test_file_path = Path(f.name)

        try:
            messages = load_transcript(test_file_path)
            # Apply deduplication (as done in convert_jsonl_to_html)
            messages = deduplicate_messages(messages)
            html = generate_html(messages, "Test Dedup")

            # Content should appear only once due to deduplication
            content_count = html.count("Slash command content")
            assert content_count == 1, (
                f"Duplicate messages should be deduplicated, found {content_count} occurrences"
            )

        finally:
            test_file_path.unlink()


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
