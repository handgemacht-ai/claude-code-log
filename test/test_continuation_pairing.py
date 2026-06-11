"""tool_use ↔ tool_result pairing must not span an assistant continuation.

When the assistant keeps talking between issuing a tool call and receiving
its (lagging) result — a ``max_tokens`` split, a thinking block, the prose
of a next turn — pair-reordering used to pull the tool_result back adjacent
to its tool_use, rendering it *before* the continuation and scrambling the
chronology the DAG linearization (``dag._is_continuation_fork``) had just
restored. In that situation the pair must not be marked at all: the
continuation renders between the tool_use and its result.

Sibling tool messages (parallel batches) and sidechain/subagent threads do
NOT block pairing — those keep the existing adjacent-pair rendering.
"""

from __future__ import annotations

import pytest

from claude_code_log.models import (
    AssistantTextMessage,
    BashInput,
    MessageMeta,
    TextContent,
    ThinkingMessage,
    ToolResultContent,
    ToolResultMessage,
    ToolUseMessage,
)
from claude_code_log.renderer import (
    RenderingContext,
    TemplateMessage,
    _identify_message_pairs,
    _reorder_paired_messages,
)


# ----------------------------- helpers ---------------------------------------


def _meta(
    uuid: str, *, ts: str = "2026-01-01T00:00:00Z", sidechain: bool = False
) -> MessageMeta:
    return MessageMeta(session_id="s", timestamp=ts, uuid=uuid, is_sidechain=sidechain)


def _tool_use(ctx: RenderingContext, uuid: str, tool_id: str) -> TemplateMessage:
    msg = TemplateMessage(
        ToolUseMessage(
            meta=_meta(uuid),
            input=BashInput(command="ls"),
            tool_use_id=tool_id,
            tool_name="Bash",
        )
    )
    ctx.register(msg)
    return msg


def _tool_result(
    ctx: RenderingContext, uuid: str, tool_id: str, *, ts: str = "2026-01-01T00:01:00Z"
) -> TemplateMessage:
    msg = TemplateMessage(
        ToolResultMessage(
            meta=_meta(uuid, ts=ts),
            tool_use_id=tool_id,
            output=ToolResultContent(
                type="tool_result", tool_use_id=tool_id, content="ok"
            ),
        )
    )
    ctx.register(msg)
    return msg


def _thinking(ctx: RenderingContext, uuid: str) -> TemplateMessage:
    msg = TemplateMessage(ThinkingMessage(meta=_meta(uuid), thinking="hmm"))
    ctx.register(msg)
    return msg


def _assistant(
    ctx: RenderingContext,
    uuid: str,
    text: str = "carrying on",
    *,
    sidechain: bool = False,
) -> TemplateMessage:
    msg = TemplateMessage(
        AssistantTextMessage(
            meta=_meta(uuid, sidechain=sidechain),
            items=[TextContent(type="text", text=text)],
        )
    )
    ctx.register(msg)
    return msg


def _empty_assistant(ctx: RenderingContext, uuid: str) -> TemplateMessage:
    msg = TemplateMessage(AssistantTextMessage(meta=_meta(uuid), items=[]))
    ctx.register(msg)
    return msg


@pytest.fixture
def ctx() -> RenderingContext:
    return RenderingContext()


# ----------------------------- pairing rule ----------------------------------


class TestContinuationBlocksToolPairing:
    def test_adjacent_pair_still_pairs(self, ctx: RenderingContext):
        use = _tool_use(ctx, "u1", "X")
        res = _tool_result(ctx, "u2", "X")
        _identify_message_pairs([use, res])
        assert use.is_first_in_pair and res.is_last_in_pair

    def test_thinking_between_blocks_pairing(self, ctx: RenderingContext):
        use = _tool_use(ctx, "u1", "X")
        think = _thinking(ctx, "u2")
        res = _tool_result(ctx, "u3", "X")
        _identify_message_pairs([use, think, res])
        assert not use.is_paired and not res.is_paired

    def test_assistant_prose_between_blocks_pairing(self, ctx: RenderingContext):
        use = _tool_use(ctx, "u1", "X")
        prose = _assistant(ctx, "u2")
        res = _tool_result(ctx, "u3", "X")
        _identify_message_pairs([use, prose, res])
        assert not use.is_paired and not res.is_paired

    def test_empty_assistant_between_does_not_block(self, ctx: RenderingContext):
        # An empty max_tokens split carries no visible content — pulling the
        # result across it changes nothing the reader can see.
        use = _tool_use(ctx, "u1", "X")
        empty = _empty_assistant(ctx, "u2")
        res = _tool_result(ctx, "u3", "X")
        _identify_message_pairs([use, empty, res])
        assert use.is_first_in_pair and res.is_last_in_pair

    def test_sidechain_thread_between_does_not_block(self, ctx: RenderingContext):
        # Task/Agent flows: the subagent's sidechain messages interleave
        # between the trunk tool_use and its result by construction.
        use = _tool_use(ctx, "u1", "X")
        side = _assistant(ctx, "u2", "subagent work", sidechain=True)
        res = _tool_result(ctx, "u3", "X")
        _identify_message_pairs([use, side, res])
        assert use.is_first_in_pair and res.is_last_in_pair

    def test_parallel_batch_still_pairs(self, ctx: RenderingContext):
        # toolA, toolB, resA, resB — sibling tool messages between A and
        # its result don't block; both pairs are marked.
        use_a = _tool_use(ctx, "u1", "A")
        use_b = _tool_use(ctx, "u2", "B")
        res_a = _tool_result(ctx, "u3", "A")
        res_b = _tool_result(ctx, "u4", "B")
        _identify_message_pairs([use_a, use_b, res_a, res_b])
        assert use_a.is_first_in_pair and res_a.is_last_in_pair
        assert use_b.is_first_in_pair and res_b.is_last_in_pair


# ----------------------------- reorder behavior ------------------------------


class TestContinuationStaysBetween:
    def test_result_not_pulled_back_across_continuation(self, ctx: RenderingContext):
        use = _tool_use(ctx, "u1", "X")
        think = _thinking(ctx, "u2")
        prose = _assistant(ctx, "u3")
        res = _tool_result(ctx, "u4", "X", ts="2026-01-01T00:02:00Z")
        messages = [use, think, prose, res]
        _identify_message_pairs(messages)
        reordered = _reorder_paired_messages(messages)
        uuids = [m.meta.uuid for m in reordered]
        assert uuids == ["u1", "u2", "u3", "u4"]

    def test_result_pulled_adjacent_without_continuation(self, ctx: RenderingContext):
        # Control: with only sibling tool messages between, the existing
        # adjacent-pair reordering still applies.
        use_a = _tool_use(ctx, "u1", "A")
        use_b = _tool_use(ctx, "u2", "B")
        res_a = _tool_result(ctx, "u3", "A")
        res_b = _tool_result(ctx, "u4", "B", ts="2026-01-01T00:02:00Z")
        messages = [use_a, use_b, res_a, res_b]
        _identify_message_pairs(messages)
        reordered = _reorder_paired_messages(messages)
        uuids = [m.meta.uuid for m in reordered]
        assert uuids == ["u1", "u3", "u2", "u4"]
