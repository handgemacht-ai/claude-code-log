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
    session_id: str = "sess-skill",
) -> dict:
    e: dict = {
        "type": "user",
        "uuid": uid,
        "parentUuid": parent,
        "timestamp": ts,
        "sessionId": session_id,
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
    session_id: str = "sess-skill",
) -> dict:
    return {
        "type": "assistant",
        "uuid": uid,
        "parentUuid": parent,
        "timestamp": ts,
        "sessionId": session_id,
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


def _assistant_text(
    uid: str,
    parent: str,
    ts: str,
    text: str,
    session_id: str = "sess-skill",
) -> dict:
    return {
        "type": "assistant",
        "uuid": uid,
        "parentUuid": parent,
        "timestamp": ts,
        "sessionId": session_id,
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

    def test_same_tool_use_id_across_sessions_does_not_cross_pair(
        self, tmp_path: Path
    ) -> None:
        """Two independent sessions reusing the same tool_use_id keep their
        Skill bodies separate. The lookup key must be (session_id, tool_use_id)
        — combined transcripts traverse multiple sessions, and Anthropic
        tool_use ids are only session-unique. A global key would let session
        B's slash body fold into session A's Skill (or vice versa) on a stray
        collision.
        """
        # Session A: Skill tool_use + body A.
        session_a = "sess-a"
        body_a = "# Body A\n\nfrom session A."
        entries_a = [
            _user(
                "ua-001",
                None,
                "2026-01-01T10:00:00Z",
                [{"type": "text", "text": "Go A"}],
                session_id=session_a,
            ),
            _assistant_tool_use(
                "aa-001",
                "ua-001",
                "2026-01-01T10:00:01Z",
                "Skill",
                "toolu_DUP",
                {"skill": "alpha"},
                session_id=session_a,
            ),
            _user(
                "ua-002",
                "aa-001",
                "2026-01-01T10:00:02Z",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_DUP",
                        "content": "Launching skill: alpha",
                        "is_error": False,
                    }
                ],
                session_id=session_a,
            ),
            _user(
                "ua-003",
                "ua-002",
                "2026-01-01T10:00:03Z",
                [{"type": "text", "text": body_a}],
                is_meta=True,
                source_tool_use_id="toolu_DUP",
                session_id=session_a,
            ),
        ]
        # Session B: same tool_use_id, different body.
        session_b = "sess-b"
        body_b = "# Body B\n\nfrom session B."
        entries_b = [
            _user(
                "ub-001",
                None,
                "2026-01-01T11:00:00Z",
                [{"type": "text", "text": "Go B"}],
                session_id=session_b,
            ),
            _assistant_tool_use(
                "ab-001",
                "ub-001",
                "2026-01-01T11:00:01Z",
                "Skill",
                "toolu_DUP",
                {"skill": "beta"},
                session_id=session_b,
            ),
            _user(
                "ub-002",
                "ab-001",
                "2026-01-01T11:00:02Z",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_DUP",
                        "content": "Launching skill: beta",
                        "is_error": False,
                    }
                ],
                session_id=session_b,
            ),
            _user(
                "ub-003",
                "ub-002",
                "2026-01-01T11:00:03Z",
                [{"type": "text", "text": body_b}],
                is_meta=True,
                source_tool_use_id="toolu_DUP",
                session_id=session_b,
            ),
        ]
        # Render both as a combined transcript.
        messages = load_transcript(
            _write_jsonl(tmp_path / "combined.jsonl", entries_a + entries_b)
        )
        _, _, ctx = generate_template_messages(messages)

        skill_uses_by_session: dict[str, ToolUseMessage] = {}
        for m in ctx.messages:
            if isinstance(m.content, ToolUseMessage) and m.content.tool_name == "Skill":
                skill_uses_by_session[m.meta.session_id] = m.content
        assert set(skill_uses_by_session) == {session_a, session_b}, (
            f"Both Skill tool_uses should survive — got {set(skill_uses_by_session)}"
        )
        # Each Skill keeps its OWN session's body, not the other session's.
        assert skill_uses_by_session[session_a].skill_body == body_a
        assert skill_uses_by_session[session_b].skill_body == body_b

    def test_error_tool_result_with_same_id_is_preserved(self, tmp_path: Path) -> None:
        """A real error tool_result sharing the Skill's tool_use_id must NOT
        be silently dropped — even though the canonical 'Launching skill:'
        result IS dropped. Without the is_error guard, a Skill that failed
        to launch would lose the error message entirely.
        """
        skill_body = "# Real Body\n\npaired with the launch result."
        entries = [
            _user(
                "u-001", None, "2026-01-01T10:00:00Z", [{"type": "text", "text": "Go"}]
            ),
            _assistant_tool_use(
                "a-001",
                "u-001",
                "2026-01-01T10:00:01Z",
                "Skill",
                "toolu_ERR",
                {"skill": "broken"},
            ),
            # Canonical "Launching skill:" result — should be dropped.
            _user(
                "u-002",
                "a-001",
                "2026-01-01T10:00:02Z",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_ERR",
                        "content": "Launching skill: broken",
                        "is_error": False,
                    }
                ],
            ),
            # Error result with the SAME tool_use_id — must survive.
            _user(
                "u-003",
                "u-002",
                "2026-01-01T10:00:03Z",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_ERR",
                        "content": "Skill 'broken' not found",
                        "is_error": True,
                    }
                ],
            ),
            _user(
                "u-004",
                "u-003",
                "2026-01-01T10:00:04Z",
                [{"type": "text", "text": skill_body}],
                is_meta=True,
                source_tool_use_id="toolu_ERR",
            ),
        ]
        messages = load_transcript(_write_jsonl(tmp_path / "t.jsonl", entries))
        _, _, ctx = generate_template_messages(messages)

        results = [
            m.content
            for m in ctx.messages
            if isinstance(m.content, ToolResultMessage)
            and m.content.tool_use_id == "toolu_ERR"
        ]
        assert len(results) == 1, (
            "Exactly the error result should survive; the canonical "
            "'Launching skill:' result should be dropped"
        )
        assert results[0].is_error is True

    def test_non_launching_skill_result_with_same_id_is_preserved(
        self, tmp_path: Path
    ) -> None:
        """A tool_result with the Skill's tool_use_id but a payload that
        does NOT start with 'Launching skill:' must NOT be dropped. The
        canonical-payload prefix check defends against a malformed transcript
        where some other content shares the id."""
        skill_body = "# Body\n\nbody text."
        entries = [
            _user(
                "u-001", None, "2026-01-01T10:00:00Z", [{"type": "text", "text": "Go"}]
            ),
            _assistant_tool_use(
                "a-001",
                "u-001",
                "2026-01-01T10:00:01Z",
                "Skill",
                "toolu_ODD",
                {"skill": "weird"},
            ),
            # Divergent (non-canonical) tool_result sharing the id — must survive.
            _user(
                "u-002",
                "a-001",
                "2026-01-01T10:00:02Z",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_ODD",
                        "content": "Some unrelated payload",
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
                source_tool_use_id="toolu_ODD",
            ),
        ]
        messages = load_transcript(_write_jsonl(tmp_path / "t.jsonl", entries))
        _, _, ctx = generate_template_messages(messages)

        results = [
            m.content
            for m in ctx.messages
            if isinstance(m.content, ToolResultMessage)
            and m.content.tool_use_id == "toolu_ODD"
        ]
        assert len(results) == 1
        # The non-canonical payload survived.
        from claude_code_log.models import ToolResultContent

        output = results[0].output
        assert isinstance(output, ToolResultContent)
        assert output.content == "Some unrelated payload"


class TestReindexBranchBackrefs:
    """Index-remap regression: ``_reindex_filtered_context`` must update
    every ``message_index`` reference, including ``parent_message_index``
    cached on branch / child ``SessionHeaderMessage`` instances.

    Background — ``_pair_skill_tool_uses`` drops slash-command bodies and
    re-indexes ``ctx.messages``. Branch headers are created earlier, in
    ``_render_messages``, and resolve the fork-point's ``message_index``
    at register time. Without remapping the cached
    ``parent_message_index``, the "from ⑂ Fork point" backlink in the
    body header jumps to whatever message ends up at the *old* index
    after the reindex shift — which surfaced as
    ``Branch • c36e76a6 from #msg-d-510`` in real transcripts where the
    fork point was actually d-496.
    """

    def test_parent_message_index_remapped(self) -> None:
        from claude_code_log.models import (
            MessageMeta,
            SessionHeaderMessage,
            UserSlashCommandMessage,
        )
        from claude_code_log.renderer import (
            RenderingContext,
            TemplateMessage,
            _reindex_filtered_context,
        )

        ctx = RenderingContext()

        def _register_user(uuid_: str, sid: str) -> TemplateMessage:
            content = UserSlashCommandMessage(
                MessageMeta(session_id=sid, timestamp="", uuid=uuid_),
                text="x",
            )
            msg = TemplateMessage(content)
            ctx.register(msg)
            return msg

        def _register_branch(
            sid: str, parent_idx: int, attachment_uuid: str
        ) -> TemplateMessage:
            content = SessionHeaderMessage(
                MessageMeta(session_id=sid, timestamp="", uuid=""),
                title="Branch • test",
                session_id=sid,
                parent_session_id="root",
                parent_message_index=parent_idx,
                attachment_uuid=attachment_uuid,
                is_branch=True,
            )
            msg = TemplateMessage(content)
            ctx.register(msg)
            return msg

        # Build: 5 messages, then a branch header pointing back to
        # message index 2 (the fork point).
        m0 = _register_user("u0", "root")  # idx 0
        m1 = _register_user("u1", "root")  # idx 1
        fork = _register_user("u2", "root")  # idx 2 — the fork point
        _register_user("u3", "root")  # idx 3 — to be dropped
        _register_user("u4", "root")  # idx 4 — to be dropped
        branch = _register_branch("root@b", parent_idx=2, attachment_uuid="u2")
        # idx 5
        assert branch.message_index is not None
        ctx.session_first_message["root"] = 0
        ctx.session_first_message["root@b"] = branch.message_index  # 5

        # Drop indices 3 and 4 (mirrors what ``_pair_skill_tool_uses``
        # does when it removes slash-command bodies + redundant
        # tool_results), then reindex.
        kept = [m0, m1, fork, branch]  # consumed1, consumed2 dropped
        _reindex_filtered_context(ctx, kept)

        # No-shift scenario: only indices 3 and 4 are dropped, so the
        # fork point at index 2 stays at index 2 — the link integrity
        # check verifies the remap *call* doesn't corrupt unshifted
        # references. The shifting case (drop an earlier index, watch
        # parent_message_index follow the shift) is covered by
        # ``test_parent_message_index_remapped_when_fork_shifts`` below.
        assert isinstance(branch.content, SessionHeaderMessage)
        new_parent_idx = branch.content.parent_message_index
        assert new_parent_idx is not None
        assert ctx.messages[new_parent_idx].meta.uuid == "u2", (
            f"Branch parent_message_index points at "
            f"{ctx.messages[new_parent_idx].meta.uuid!r}, expected u2"
        )

    def test_parent_message_index_remapped_when_fork_shifts(self) -> None:
        """Reindex shifts the fork-point's index when an earlier message
        is dropped. The branch backlink must follow the shift."""
        from claude_code_log.models import (
            MessageMeta,
            SessionHeaderMessage,
            UserSlashCommandMessage,
        )
        from claude_code_log.renderer import (
            RenderingContext,
            TemplateMessage,
            _reindex_filtered_context,
        )

        ctx = RenderingContext()

        def _user(uuid_: str) -> TemplateMessage:
            msg = TemplateMessage(
                UserSlashCommandMessage(
                    MessageMeta(session_id="root", timestamp="", uuid=uuid_),
                    text="x",
                )
            )
            ctx.register(msg)
            return msg

        m0 = _user("u0")  # idx 0
        _user("u1")  # idx 1 — to be dropped
        fork = _user("u2")  # idx 2
        m3 = _user("u3")  # idx 3
        branch_msg = TemplateMessage(
            SessionHeaderMessage(
                MessageMeta(session_id="root@b", timestamp="", uuid=""),
                title="Branch",
                session_id="root@b",
                parent_session_id="root",
                parent_message_index=2,  # points at fork
                attachment_uuid="u2",
                is_branch=True,
            )
        )
        ctx.register(branch_msg)  # idx 4

        # Drop m1; fork's new index becomes 1, branch becomes 3.
        _reindex_filtered_context(ctx, [m0, fork, m3, branch_msg])

        assert fork.message_index == 1
        assert isinstance(branch_msg.content, SessionHeaderMessage)
        assert branch_msg.content.parent_message_index == 1, (
            "Branch parent_message_index should follow the fork point "
            "to its new index after reindex"
        )


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

    def test_skill_title_folds_skill_name(self, tmp_path: Path) -> None:
        """Title surfaces ``💡 Skill <name>`` and the params row is suppressed."""
        messages = load_transcript(
            _skill_invocation_jsonl(
                tmp_path / "t.jsonl", skill_name="clmail:read", skill_body="# body"
            )
        )
        html = HtmlRenderer().generate(messages, "Skill pairing HTML")

        # Title carries the skill-name as the tool-summary span next to "Skill"
        assert "💡 Skill" in html
        assert "clmail:read" in html
        # No params table row labelled "skill"
        assert ">skill</td>" not in html

    def test_skill_with_extra_args_field_still_typed(self, tmp_path: Path) -> None:
        """Real Skill invocations carry an ``args`` string alongside ``skill``;
        the typed model must accept that without falling back to ToolUseContent."""
        messages = load_transcript(
            _skill_invocation_jsonl(
                tmp_path / "t.jsonl", skill_name="my-worktree-actors", skill_body="x"
            )
        )
        html = HtmlRenderer().generate(messages, "Skill pairing HTML")
        # The fixture passes `{"skill": skill_name, "args": ""}` (see
        # `_skill_invocation_jsonl`); without `extra="allow"` on SkillInput,
        # validation would fail and the message would render with the generic
        # tool emoji 🛠️ instead of the skill-specific 💡.
        assert "💡 Skill" in html


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

    def test_skill_title_folds_skill_name(self, tmp_path: Path) -> None:
        messages = load_transcript(
            _skill_invocation_jsonl(
                tmp_path / "t.jsonl", skill_name="clmail:read", skill_body="# body"
            )
        )
        md = MarkdownRenderer().generate(messages, "Skill pairing MD")
        assert "💡 Skill `clmail:read`" in md
