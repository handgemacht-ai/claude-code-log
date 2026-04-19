"""Tests for Skill tool_use / isMeta slash-command pairing (issue #93).

Claude Code's Skill invocation produces three discrete entries in the
transcript:

1. assistant `Skill` tool_use (one row)
2. user tool_result with the literal text "Launching skill: <name>"
3. user `isMeta=True` entry whose `sourceToolUseID` matches (1) and
   whose text is the expanded skill body (markdown, 100+ lines)

`_pair_skill_tool_uses` in `renderer.py` folds (3) into (1) as
`ToolUseMessage.skill_body` and drops (2) and (3) from `ctx.messages`
so the Skill invocation renders as a single visual unit.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from claude_code_log.converter import load_transcript
from claude_code_log.html.renderer import HtmlRenderer
from claude_code_log.markdown.renderer import MarkdownRenderer
from claude_code_log.models import (
    ToolResultMessage,
    ToolUseMessage,
    UserSlashCommandMessage,
)
from claude_code_log.renderer import generate_template_messages


# -- Fixtures ----------------------------------------------------------------


def _user(
    uid: str,
    parent: str | None,
    ts: str,
    content: list[dict],
    is_meta: bool = False,
    source_tool_use_id: str | None = None,
) -> dict:
    e: dict = {
        "type": "user",
        "uuid": uid,
        "parentUuid": parent,
        "timestamp": ts,
        "sessionId": "sess-skill",
        "isSidechain": False,
        "userType": "external",
        "cwd": "/tmp",
        "version": "1.0",
        "message": {"role": "user", "content": content},
    }
    if is_meta:
        e["isMeta"] = True
    if source_tool_use_id is not None:
        e["sourceToolUseID"] = source_tool_use_id
    return e


def _assistant_tool_use(
    uid: str,
    parent: str,
    ts: str,
    tool_name: str,
    tool_use_id: str,
    input_obj: dict,
) -> dict:
    return {
        "type": "assistant",
        "uuid": uid,
        "parentUuid": parent,
        "timestamp": ts,
        "sessionId": "sess-skill",
        "isSidechain": False,
        "userType": "external",
        "cwd": "/tmp",
        "version": "1.0",
        "requestId": f"req_{uid}",
        "message": {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": input_obj,
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    }


def _assistant_text(uid: str, parent: str, ts: str, text: str) -> dict:
    return {
        "type": "assistant",
        "uuid": uid,
        "parentUuid": parent,
        "timestamp": ts,
        "sessionId": "sess-skill",
        "isSidechain": False,
        "userType": "external",
        "cwd": "/tmp",
        "version": "1.0",
        "requestId": f"req_{uid}",
        "message": {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    }


def _write_jsonl(path: Path, entries: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def _skill_invocation_jsonl(
    path: Path,
    skill_name: str = "my-skill",
    skill_body: str = "# My Skill\n\nThe **body** of the skill.",
    tool_use_id: str = "toolu_SKILL_A",
) -> Path:
    entries = [
        _user("u-001", None, "2026-01-01T10:00:00Z", [{"type": "text", "text": "Go"}]),
        _assistant_tool_use(
            "a-001",
            "u-001",
            "2026-01-01T10:00:01Z",
            "Skill",
            tool_use_id,
            {"skill": skill_name, "args": ""},
        ),
        _user(
            "u-002",
            "a-001",
            "2026-01-01T10:00:02Z",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": f"Launching skill: {skill_name}",
                    "is_error": False,
                }
            ],
        ),
        _user(
            "u-003",
            "u-002",
            "2026-01-01T10:00:03Z",
            [{"type": "text", "text": skill_body}],
            is_meta=True,
            source_tool_use_id=tool_use_id,
        ),
        _assistant_text("a-002", "u-003", "2026-01-01T10:00:04Z", "Skill ran."),
    ]
    return _write_jsonl(path, entries)


# -- Template-level pairing --------------------------------------------------


class TestSkillPairing:
    """The three-entity Skill pattern collapses to one ToolUseMessage."""

    def test_skill_body_folded_into_tool_use(self, tmp_path: Path) -> None:
        body = "# Read Mail\n\nReads and displays **mail** by ID."
        messages = load_transcript(
            _skill_invocation_jsonl(
                tmp_path / "t.jsonl", skill_name="clmail:read", skill_body=body
            )
        )

        _, _, ctx = generate_template_messages(messages)

        skill_tool_uses = [
            m.content
            for m in ctx.messages
            if isinstance(m.content, ToolUseMessage) and m.content.tool_name == "Skill"
        ]
        assert len(skill_tool_uses) == 1
        assert skill_tool_uses[0].skill_body == body

    def test_slash_command_consumed(self, tmp_path: Path) -> None:
        messages = load_transcript(_skill_invocation_jsonl(tmp_path / "t.jsonl"))
        _, _, ctx = generate_template_messages(messages)

        slash = [
            m for m in ctx.messages if isinstance(m.content, UserSlashCommandMessage)
        ]
        assert slash == [], (
            f"UserSlashCommandMessage should be consumed when paired; got "
            f"{[type(m.content).__name__ for m in ctx.messages]}"
        )

    def test_launching_skill_tool_result_dropped(self, tmp_path: Path) -> None:
        messages = load_transcript(
            _skill_invocation_jsonl(tmp_path / "t.jsonl", tool_use_id="toolu_X")
        )
        _, _, ctx = generate_template_messages(messages)

        tr = [
            m
            for m in ctx.messages
            if isinstance(m.content, ToolResultMessage) and m.tool_use_id == "toolu_X"
        ]
        assert tr == [], (
            "The redundant 'Launching skill: X' tool_result should be dropped"
        )

    def test_non_skill_tool_use_unchanged(self, tmp_path: Path) -> None:
        """Other tool_use entries (e.g. Bash) keep their separate tool_result."""
        entries = [
            _user(
                "u-001", None, "2026-01-01T10:00:00Z", [{"type": "text", "text": "Go"}]
            ),
            _assistant_tool_use(
                "a-001",
                "u-001",
                "2026-01-01T10:00:01Z",
                "Bash",
                "toolu_BASH_1",
                {"command": "echo hi"},
            ),
            _user(
                "u-002",
                "a-001",
                "2026-01-01T10:00:02Z",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_BASH_1",
                        "content": "hi",
                        "is_error": False,
                    }
                ],
            ),
        ]
        messages = load_transcript(_write_jsonl(tmp_path / "t.jsonl", entries))
        _, _, ctx = generate_template_messages(messages)

        tool_uses = [
            m.content for m in ctx.messages if isinstance(m.content, ToolUseMessage)
        ]
        results = [m for m in ctx.messages if isinstance(m.content, ToolResultMessage)]
        assert len(tool_uses) == 1
        assert tool_uses[0].skill_body is None
        assert len(results) == 1  # Bash tool_result is NOT dropped

    def test_meta_without_source_tool_use_id_unchanged(self, tmp_path: Path) -> None:
        """isMeta=True entries without sourceToolUseID render as slash-commands."""
        entries = [
            _user(
                "u-001", None, "2026-01-01T10:00:00Z", [{"type": "text", "text": "Go"}]
            ),
            _user(
                "u-002",
                "u-001",
                "2026-01-01T10:00:01Z",
                [{"type": "text", "text": "# Standalone meta\n\nNot a skill body."}],
                is_meta=True,
                # no sourceToolUseID
            ),
        ]
        messages = load_transcript(_write_jsonl(tmp_path / "t.jsonl", entries))
        _, _, ctx = generate_template_messages(messages)

        slash = [
            m for m in ctx.messages if isinstance(m.content, UserSlashCommandMessage)
        ]
        assert len(slash) == 1  # Still rendered as a standalone slash-command

    def test_orphan_skill_body_unpaired(self, tmp_path: Path) -> None:
        """If the matching Skill tool_use is missing, the body survives as-is."""
        entries = [
            _user(
                "u-001", None, "2026-01-01T10:00:00Z", [{"type": "text", "text": "Go"}]
            ),
            _user(
                "u-002",
                "u-001",
                "2026-01-01T10:00:01Z",
                [{"type": "text", "text": "# Orphan\n\nNo tool_use with this id."}],
                is_meta=True,
                source_tool_use_id="toolu_MISSING",
            ),
        ]
        messages = load_transcript(_write_jsonl(tmp_path / "t.jsonl", entries))
        _, _, ctx = generate_template_messages(messages)

        slash = [
            m for m in ctx.messages if isinstance(m.content, UserSlashCommandMessage)
        ]
        # No pair found → slash-command is not consumed, renders standalone.
        assert len(slash) == 1


# -- Renderer output ---------------------------------------------------------


class TestSkillPairingHtml:
    def test_skill_body_appears_in_tool_use_block(self, tmp_path: Path) -> None:
        body = "# Mail reader\n\nReads a mail by **id**."
        messages = load_transcript(
            _skill_invocation_jsonl(
                tmp_path / "t.jsonl", skill_name="clmail:read", skill_body=body
            )
        )
        html = HtmlRenderer().generate(messages, "Skill pairing HTML")

        # Body is rendered as markdown inside the skill-body container
        assert "skill-body" in html
        assert "<strong>id</strong>" in html  # ** → <strong>
        assert "Mail reader" in html
        # Standalone slash-command rendering is gone — no slash-command CSS class
        # on a top-level message (the class only appears inside the skill-body
        # container's rendered markdown, which doesn't use it).
        # The redundant "Launching skill" string is gone too.
        assert "Launching skill" not in html


class TestSkillPairingMarkdown:
    def test_skill_body_appears_under_tool_use(self, tmp_path: Path) -> None:
        body = "# Mail reader\n\nReads a mail by **id**."
        messages = load_transcript(
            _skill_invocation_jsonl(
                tmp_path / "t.jsonl", skill_name="clmail:read", skill_body=body
            )
        )
        md = MarkdownRenderer().generate(messages, "Skill pairing MD")

        # Markdown body passes through verbatim.
        assert "# Mail reader" in md
        assert "**id**" in md
        assert "Launching skill" not in md
