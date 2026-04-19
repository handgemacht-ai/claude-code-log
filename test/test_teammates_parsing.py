"""Parser tests for the teammates feature (issue #91, PR #117)."""

from __future__ import annotations

from claude_code_log.factories.agent_metadata_factory import (
    parse_agent_result_metadata,
)
from claude_code_log.factories.teammate_factory import (
    create_teammate_message,
    find_team_lead_body,
    has_teammate_message,
    iter_teammate_blocks,
)
from claude_code_log.factories.tool_factory import (
    TOOL_INPUT_MODELS,
    TOOL_OUTPUT_PARSERS,
    create_tool_input,
    parse_sendmessage_output,
    parse_taskcreate_output,
    parse_tasklist_output,
    parse_taskupdate_output,
    parse_teamcreate_output,
    parse_teamdelete_output,
)
from claude_code_log.models import (
    AgentResultMetadata,
    MessageMeta,
    SendMessageInput,
    SendMessageOutput,
    TaskCreateInput,
    TaskCreateOutput,
    TaskListInput,
    TaskListOutput,
    TaskUpdateInput,
    TaskUpdateOutput,
    TeamCreateInput,
    TeamCreateOutput,
    TeamDeleteInput,
    TeamDeleteOutput,
    ToolResultContent,
)


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


def _meta() -> MessageMeta:
    return MessageMeta(session_id="s", timestamp="t", uuid="u")


SINGLE_BLOCK = (
    '<teammate-message teammate_id="alice" color="blue" '
    'summary="relay tests complete">\n'
    "Relay coverage is now 96%.\n"
    "</teammate-message>"
)

MULTI_BLOCK = (
    '<teammate-message teammate_id="alice" color="blue">\n'
    "alice heartbeat: still here.\n"
    "</teammate-message>\n\n"
    '<teammate-message teammate_id="bob" color="green" summary="done">\n'
    "All server tests pass.\n"
    "</teammate-message>\n\n"
    '<teammate-message teammate_id="system">\n'
    "teammate_terminated: alice exited cleanly\n"
    "</teammate-message>"
)


class TestTeammateMessageParser:
    def test_has_teammate_message_detects(self) -> None:
        assert has_teammate_message(SINGLE_BLOCK) is True
        assert has_teammate_message("no tags here") is False
        assert has_teammate_message("<teammate-message") is False  # no close tag

    def test_iter_returns_blocks_in_order(self) -> None:
        ids = [b.teammate_id for b in iter_teammate_blocks(MULTI_BLOCK)]
        assert ids == ["alice", "bob", "system"]

    def test_single_block_attributes_and_body(self) -> None:
        blocks = list(iter_teammate_blocks(SINGLE_BLOCK))
        assert len(blocks) == 1
        b = blocks[0]
        assert b.teammate_id == "alice"
        assert b.color == "blue"
        assert b.summary == "relay tests complete"
        assert b.body == "Relay coverage is now 96%."
        assert b.is_system is False

    def test_block_without_summary(self) -> None:
        text = (
            '<teammate-message teammate_id="alice" color="blue">\n'
            "plain body\n"
            "</teammate-message>"
        )
        b = next(iter_teammate_blocks(text))
        assert b.summary is None
        assert b.color == "blue"

    def test_system_block_flagged(self) -> None:
        blocks = list(iter_teammate_blocks(MULTI_BLOCK))
        system_block = blocks[-1]
        assert system_block.is_system is True
        assert "teammate_terminated" in system_block.body

    def test_create_returns_none_without_block(self) -> None:
        assert create_teammate_message(_meta(), "just some text") is None

    def test_create_batch_single_block(self) -> None:
        content = create_teammate_message(_meta(), SINGLE_BLOCK)
        assert content is not None
        assert len(content.blocks) == 1
        assert content.blocks[0].teammate_id == "alice"
        assert content.leading_text is None
        assert content.trailing_text is None
        assert content.message_type == "teammate"
        assert content.has_markdown is True

    def test_create_batch_mixed_teammates(self) -> None:
        content = create_teammate_message(_meta(), MULTI_BLOCK)
        assert content is not None
        assert [b.teammate_id for b in content.blocks] == ["alice", "bob", "system"]

    def test_leading_and_trailing_text_preserved(self) -> None:
        text = f"Before text\n\n{SINGLE_BLOCK}\n\nAfter text"
        content = create_teammate_message(_meta(), text)
        assert content is not None
        assert content.leading_text == "Before text"
        assert content.trailing_text == "After text"

    def test_find_team_lead_body(self) -> None:
        wrapped = (
            '<teammate-message teammate_id="team-lead" color="cyan">\n'
            "do the thing\n"
            "</teammate-message>"
        )
        assert find_team_lead_body(wrapped) == "do the thing"
        assert find_team_lead_body(SINGLE_BLOCK) is None
        assert find_team_lead_body("") is None


def _tr_text(text: str) -> ToolResultContent:
    """Build a ToolResultContent with a single text block body."""
    return ToolResultContent(
        type="tool_result",
        tool_use_id="tu_fake",
        content=[{"type": "text", "text": text}],
    )


class TestTeammateToolInputs:
    """All six teammate tool names route to a typed BaseModel input."""

    def test_inputs_registered(self) -> None:
        for name, cls in {
            "TeamCreate": TeamCreateInput,
            "TeamDelete": TeamDeleteInput,
            "TaskCreate": TaskCreateInput,
            "TaskUpdate": TaskUpdateInput,
            "TaskList": TaskListInput,
            "SendMessage": SendMessageInput,
        }.items():
            assert TOOL_INPUT_MODELS.get(name) is cls, f"{name} not mapped"

    def test_teamcreate_input(self) -> None:
        parsed = create_tool_input(
            "TeamCreate",
            {
                "team_name": "x",
                "description": "d",
                "agent_type": "team-lead",
            },
        )
        assert isinstance(parsed, TeamCreateInput)
        assert parsed.team_name == "x"
        assert parsed.agent_type == "team-lead"

    def test_taskupdate_input_partial(self) -> None:
        parsed = create_tool_input("TaskUpdate", {"taskId": "1", "status": "completed"})
        assert isinstance(parsed, TaskUpdateInput)
        assert parsed.taskId == "1"
        assert parsed.status == "completed"
        assert parsed.owner is None

    def test_tasklist_input_empty(self) -> None:
        parsed = create_tool_input("TaskList", {})
        assert isinstance(parsed, TaskListInput)

    def test_sendmessage_input(self) -> None:
        parsed = create_tool_input(
            "SendMessage",
            {
                "type": "shutdown_request",
                "recipient": "alice",
                "content": "go home",
            },
        )
        assert isinstance(parsed, SendMessageInput)
        assert parsed.recipient == "alice"
        assert parsed.content == "go home"


class TestTeammateToolOutputs:
    """JSON/plain-text tool results parse into typed outputs."""

    def test_output_parsers_registered(self) -> None:
        for name in (
            "TeamCreate",
            "TeamDelete",
            "TaskCreate",
            "TaskUpdate",
            "TaskList",
            "SendMessage",
        ):
            assert name in TOOL_OUTPUT_PARSERS, f"{name} parser missing"

    def test_teamcreate_output(self) -> None:
        payload = (
            '{"team_name":"test-coverage",'
            '"team_file_path":"/teams/test-coverage/config.json",'
            '"lead_agent_id":"team-lead@test-coverage"}'
        )
        out = parse_teamcreate_output(_tr_text(payload), None)
        assert isinstance(out, TeamCreateOutput)
        assert out.team_name == "test-coverage"
        assert out.lead_agent_id == "team-lead@test-coverage"

    def test_teamcreate_output_rejects_non_json(self) -> None:
        out = parse_teamcreate_output(_tr_text("not-json"), None)
        assert out is None

    def test_teamdelete_extracts_active_members(self) -> None:
        payload = (
            '{"success":false,'
            '"message":"Cannot cleanup team with 2 active member(s): alice, bob. Try shutdown first.",'
            '"team_name":"test-coverage"}'
        )
        out = parse_teamdelete_output(_tr_text(payload), None)
        assert isinstance(out, TeamDeleteOutput)
        assert out.success is False
        assert out.active_members == ["alice", "bob"]
        assert out.team_name == "test-coverage"

    def test_teamdelete_success_no_members(self) -> None:
        payload = '{"success":true,"message":"Team deleted.","team_name":"x"}'
        out = parse_teamdelete_output(_tr_text(payload), None)
        assert isinstance(out, TeamDeleteOutput)
        assert out.success is True
        assert out.active_members is None

    def test_taskcreate_output(self) -> None:
        out = parse_taskcreate_output(
            _tr_text("Task #3 created successfully: Add relay tests"),
            None,
        )
        assert isinstance(out, TaskCreateOutput)
        assert out.task_id == "3"
        assert out.subject == "Add relay tests"

    def test_taskcreate_rejects_unrecognized(self) -> None:
        out = parse_taskcreate_output(_tr_text("Completely different"), None)
        assert out is None

    def test_taskupdate_output(self) -> None:
        out = parse_taskupdate_output(_tr_text("Updated task #1 owner, status"), None)
        assert isinstance(out, TaskUpdateOutput)
        assert out.success is True
        assert out.task_id == "1"
        assert out.updated_fields == {"owner": True, "status": True}

    def test_tasklist_output(self) -> None:
        text = (
            "#1 [completed] Add relay tests (alice)\n"
            "#2 [in_progress] Add server tests (bob)\n"
            "#3 [pending] Merge branches"
        )
        out = parse_tasklist_output(_tr_text(text), None)
        assert isinstance(out, TaskListOutput)
        assert len(out.tasks) == 3
        assert out.tasks[0].status == "completed"
        assert out.tasks[0].owner == "alice"
        assert out.tasks[2].owner is None

    def test_tasklist_returns_none_on_unknown_format(self) -> None:
        out = parse_tasklist_output(_tr_text("This is not a task list."), None)
        assert out is None

    def test_sendmessage_output(self) -> None:
        payload = (
            '{"success":true,'
            '"message":"Shutdown request sent to alice.",'
            '"request_id":"shutdown-1@alice",'
            '"target":"alice"}'
        )
        out = parse_sendmessage_output(_tr_text(payload), None)
        assert isinstance(out, SendMessageOutput)
        assert out.success is True
        assert out.target == "alice"
        assert out.request_id == "shutdown-1@alice"
