"""Parser tests for the teammates feature (issue #91, PR #117)."""

from __future__ import annotations

from claude_code_log.factories.agent_metadata_factory import (
    parse_agent_result_metadata,
)
from claude_code_log.models import AgentResultMetadata


class TestAgentResultMetadata:
    def test_returns_none_for_plain_text(self) -> None:
        body, meta = parse_agent_result_metadata("Hello, world.")
        assert body == "Hello, world."
        assert meta is None

    def test_returns_none_for_empty(self) -> None:
        body, meta = parse_agent_result_metadata("")
        assert body == ""
        assert meta is None

    def test_parses_agent_id_only(self) -> None:
        text = "Done.\n\nagentId: abc123\n"
        body, meta = parse_agent_result_metadata(text)
        assert body == "Done."
        assert meta is not None
        assert meta.agent_id == "abc123"
        assert meta.worktree_path is None
        assert meta.total_tokens is None

    def test_parses_agent_id_with_trailing_sendmessage_hint(self) -> None:
        text = (
            "Work complete.\n"
            "agentId: a4ca7529 (use SendMessage with to: 'x' to continue this agent)\n"
        )
        body, meta = parse_agent_result_metadata(text)
        assert body == "Work complete."
        assert meta is not None
        # Hint in parens must not be absorbed into the id
        assert meta.agent_id == "a4ca7529"

    def test_parses_worktree_fields(self) -> None:
        text = (
            "Body text.\n"
            "agentId: xyz\n"
            "worktreePath: /home/user/worktrees/agent-xyz\n"
            "worktreeBranch: worktree-agent-xyz\n"
        )
        body, meta = parse_agent_result_metadata(text)
        assert body == "Body text."
        assert meta is not None
        assert meta.agent_id == "xyz"
        assert meta.worktree_path == "/home/user/worktrees/agent-xyz"
        assert meta.worktree_branch == "worktree-agent-xyz"

    def test_parses_usage_block(self) -> None:
        text = (
            "agent response\n"
            "agentId: a\n"
            "worktreePath: /tmp/a\n"
            "worktreeBranch: b-a\n"
            "<usage>total_tokens: 48421\n"
            "tool_uses: 24\n"
            "duration_ms: 802753</usage>"
        )
        body, meta = parse_agent_result_metadata(text)
        assert body == "agent response"
        assert meta is not None
        assert meta.total_tokens == 48421
        assert meta.tool_uses == 24
        assert meta.duration_ms == 802753

    def test_usage_block_only(self) -> None:
        """Pre-teammates transcripts may have <usage> alone."""
        text = (
            "Answer.\n<usage>total_tokens: 10\ntool_uses: 1\nduration_ms: 200</usage>"
        )
        body, meta = parse_agent_result_metadata(text)
        assert body == "Answer."
        assert meta is not None
        assert meta.agent_id is None
        assert meta.total_tokens == 10
        assert meta.tool_uses == 1
        assert meta.duration_ms == 200

    def test_metadata_tail_is_stripped_idempotently(self) -> None:
        text = "Body\n\n\nagentId: x\nworktreePath: /p\n"
        body, meta = parse_agent_result_metadata(text)
        assert body == "Body"
        # Feeding the stripped body back yields None (no tail left).
        _, second = parse_agent_result_metadata(body)
        assert second is None

    def test_result_object_type(self) -> None:
        _, meta = parse_agent_result_metadata("agentId: abc\n")
        assert isinstance(meta, AgentResultMetadata)
