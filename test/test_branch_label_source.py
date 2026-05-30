"""Regression tests for branch-preview sourcing in ``_build_branch_header``.

The branch ``SessionHeaderMessage.preview`` (which feeds the body
header title, the session/graph index, and the fork-point box's
backlink — all of which must agree on ``Branch • <uuid8> •
<preview>``) is computed once by scanning the branch DAG-line for the
first user entry with non-empty text, via ``extract_text_content``
plus ``create_session_preview``.

These tests pin two cases the single-source rule must handle:

1. **Branch starts with an assistant turn** — the scan must walk past
   the first entry (no user text) and pick up the later user entry's
   preview. This is the case the now-deleted ``_enrich_branch_titles``
   post-pass used to back-fill.
2. **Branch starts with a slash-command user entry** — #129
   precedence: the slash-command body (e.g. ``/exit``) is the first
   user entry with text, so the scan picks it before any later
   user turn ever gets considered. Length is irrelevant — DAG order
   is the precedence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from claude_code_log.converter import load_directory_transcripts
from claude_code_log.models import SessionHeaderMessage
from claude_code_log.renderer import TemplateMessage, generate_template_messages


# ----- fixture builders ----------------------------------------------------


def _user_entry(
    uuid: str,
    parent_uuid: str | None,
    text: str,
    *,
    session_id: str = "s1",
    timestamp: str,
) -> dict[str, Any]:
    return {
        "type": "user",
        "uuid": uuid,
        "timestamp": timestamp,
        "parentUuid": parent_uuid,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": session_id,
        "version": "1.0.0",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def _assistant_entry(
    uuid: str,
    parent_uuid: str | None,
    text: str,
    *,
    session_id: str = "s1",
    timestamp: str,
    request_id: str,
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": uuid,
        "timestamp": timestamp,
        "parentUuid": parent_uuid,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": session_id,
        "version": "1.0.0",
        "requestId": request_id,
        "message": {
            "id": uuid,
            "type": "message",
            "role": "assistant",
            "model": "claude-3-sonnet",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }


def _write_jsonl(path: Path, raw_entries: Iterable[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for entry in raw_entries:
            fh.write(json.dumps(entry) + "\n")


def _branch_headers(roots: list[TemplateMessage]) -> list[SessionHeaderMessage]:
    """Walk the rendered tree and return all branch SessionHeaderMessages
    (any depth — within-fork branch headers hang under their parent)."""

    def walk(messages: list[TemplateMessage]):
        for msg in messages:
            yield msg
            yield from walk(msg.children)

    return [
        msg.content
        for msg in walk(roots)
        if isinstance(msg.content, SessionHeaderMessage) and msg.content.is_branch
    ]


# ----- the tests -----------------------------------------------------------


class TestBranchPreviewFromDagLineScan:
    """Pin that ``_build_branch_header`` computes the branch preview by
    scanning the DAG-line uuids for the first user entry with text."""

    def test_branch_starting_with_assistant_uses_later_user_text(
        self, tmp_path: Path
    ) -> None:
        """A within-session fork whose first entry is an assistant turn
        ("No response requested." after ``/exit`` is the canonical
        production case) must still produce a non-empty preview by
        scanning forward through the branch DAG-line to the next
        user entry with text.

        Before the single-source rewrite, ``_render_messages`` left the
        preview empty for this case and a separate ``_enrich_branch_titles``
        post-pass back-filled it. The new code does the scan up front
        in ``_build_branch_header``.
        """
        # trunk: a (user) → b (assistant) → c (user "Fork point")
        # branch off c, two children — both assistants so the DAG
        # fork-collapse "tool-result side-branch" heuristic
        # (``_stitch_tool_results``, which needs one user and one
        # assistant child) doesn't stitch them and we get a real
        # fork with two branches:
        #   branch 1: d (assistant) → e (user "user text after assistant")
        #   branch 2: f (assistant) — disambiguating sibling
        entries = [
            _user_entry("a", None, "Hello", timestamp="2025-07-01T10:00:00Z"),
            _assistant_entry(
                "b", "a", "Hi", timestamp="2025-07-01T10:01:00Z", request_id="r1"
            ),
            _user_entry("c", "b", "Fork point", timestamp="2025-07-01T10:02:00Z"),
            # branch 1: assistant-first
            _assistant_entry(
                "d",
                "c",
                "Branch 1 leading assistant",
                timestamp="2025-07-01T10:03:00Z",
                request_id="r2",
            ),
            _user_entry(
                "e",
                "d",
                "user text after assistant",
                timestamp="2025-07-01T10:04:00Z",
            ),
            # branch 2: another assistant sibling (see comment above
            # — both children must be the same role to bypass the
            # tool-result stitch and produce a genuine fork)
            _assistant_entry(
                "f",
                "c",
                "alt branch first reply",
                timestamp="2025-07-01T10:05:00Z",
                request_id="r3",
            ),
        ]
        project_dir = tmp_path / "asst-start-project"
        project_dir.mkdir()
        _write_jsonl(project_dir / "s1.jsonl", entries)

        result, session_tree = load_directory_transcripts(project_dir, silent=True)
        roots, _nav, _ctx = generate_template_messages(
            result, session_tree=session_tree
        )

        branch_contents = _branch_headers(roots)
        # Find the branch whose first uuid is 'd' (the assistant-start one).
        asst_first = [b for b in branch_contents if b.first_uuid == "d"]
        assert asst_first, (
            "expected a branch header rooted at uuid 'd' (the assistant-start "
            f"branch); got branches: {[(b.first_uuid, b.preview) for b in branch_contents]}"
        )
        b = asst_first[0]
        assert b.preview == "user text after assistant", (
            "assistant-start branch must scan the DAG-line to the next user "
            f"entry with text; got preview={b.preview!r}"
        )
        # And the assembled title carries the same preview.
        assert "user text after assistant" in (b.title or "")

    def test_branch_starting_with_slash_command_preserves_129_precedence(
        self, tmp_path: Path
    ) -> None:
        """A within-session fork whose first entry is a user-typed
        slash command (e.g. ``/exit``, surfaced as the cleaned 5-char
        form by ``create_session_preview`` → ``simplify_command_tags``)
        must have THAT as its preview — not any later, longer-but-less-
        informative user turn. The DAG-order scan picks the first user
        entry with text and breaks; this structurally preserves the
        #129 precedence rule (see ``test_utils.py::test_create_session_
        preview_strips_slash_command_xml``).
        """
        slash_body = (
            "<command-name>/exit</command-name>"
            "<command-message>exit</command-message>"
            "<command-args></command-args>"
        )
        # trunk: a → b → c (fork point)
        # branch 1: d = /exit (user) → e (assistant "ack") → g (user "Much later, longer, less informative user reply")
        # branch 2: f (user)         — sibling so c is a real junction
        entries = [
            _user_entry("a", None, "Hello", timestamp="2025-07-01T10:00:00Z"),
            _assistant_entry(
                "b", "a", "Hi", timestamp="2025-07-01T10:01:00Z", request_id="r1"
            ),
            _user_entry("c", "b", "Fork point", timestamp="2025-07-01T10:02:00Z"),
            # branch 1: slash-command first
            _user_entry("d", "c", slash_body, timestamp="2025-07-01T10:03:00Z"),
            _assistant_entry(
                "e", "d", "ack", timestamp="2025-07-01T10:04:00Z", request_id="r2"
            ),
            _user_entry(
                "g",
                "e",
                "Much later, longer, less informative user reply that we must not pick",
                timestamp="2025-07-01T10:05:00Z",
            ),
            # branch 2 sibling
            _user_entry("f", "c", "second branch", timestamp="2025-07-01T10:06:00Z"),
        ]
        project_dir = tmp_path / "slash-first-project"
        project_dir.mkdir()
        _write_jsonl(project_dir / "s1.jsonl", entries)

        result, session_tree = load_directory_transcripts(project_dir, silent=True)
        roots, _nav, _ctx = generate_template_messages(
            result, session_tree=session_tree
        )

        branch_contents = _branch_headers(roots)
        slash_first = [b for b in branch_contents if b.first_uuid == "d"]
        assert slash_first, (
            "expected a branch header rooted at uuid 'd' (the slash-command-start "
            f"branch); got branches: {[(b.first_uuid, b.preview) for b in branch_contents]}"
        )
        b = slash_first[0]
        assert b.preview == "/exit", (
            "slash-command branch root must surface as the cleaned '/exit' "
            f"form (#129); got preview={b.preview!r}. A length-based pick "
            "would wrongly choose the later longer reply."
        )
        # Title carries the cleaned form, NOT the raw <command-name> XML.
        assert "/exit" in (b.title or "")
        assert "<command-name>" not in (b.title or "")
        assert "Much later" not in (b.title or "")
