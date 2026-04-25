"""Tests for adjacent SlashCommand ↔ UserSlashCommand pairing (issue #126).

A `Slash Command` (the typed `/cmd`) and the corresponding
`User (slash command)` (expanded prompt or system caveat) represent a
single logical event and must render as a paired unit. They can appear
in either order:

    `/init`  →  Slash Command  then  User (slash command)
    `/exit`  →  User (slash command)  (caveat)  then  Slash Command
"""

from __future__ import annotations

import pytest

from claude_code_log.models import (
    CommandOutputMessage,
    MessageMeta,
    SlashCommandMessage,
    UserSlashCommandMessage,
)
from claude_code_log.renderer import (
    RenderingContext,
    TemplateMessage,
    _identify_message_pairs,
    _try_pair_adjacent,
)


# ----------------------------- helpers ---------------------------------------


def _meta(uuid: str, *, ts: str = "2026-01-01T00:00:00Z") -> MessageMeta:
    return MessageMeta(session_id="s", timestamp=ts, uuid=uuid)


def _slash(ctx: RenderingContext, uuid: str, name: str = "init") -> TemplateMessage:
    msg = TemplateMessage(
        SlashCommandMessage(
            meta=_meta(uuid),
            command_name=name,
            command_args="",
            command_contents="",
        )
    )
    ctx.register(msg)
    return msg


def _user_slash(
    ctx: RenderingContext, uuid: str, text: str = "expanded prompt"
) -> TemplateMessage:
    meta = _meta(uuid)
    meta.is_meta = True
    msg = TemplateMessage(UserSlashCommandMessage(meta=meta, text=text))
    ctx.register(msg)
    return msg


def _cmd_output(
    ctx: RenderingContext, uuid: str, stdout: str = "ok"
) -> TemplateMessage:
    msg = TemplateMessage(
        CommandOutputMessage(meta=_meta(uuid), stdout=stdout, is_markdown=False)
    )
    ctx.register(msg)
    return msg


@pytest.fixture
def ctx() -> RenderingContext:
    return RenderingContext()


# ----------------------------- _try_pair_adjacent ----------------------------


class TestSlashCommandAdjacentPairing:
    """Pair the slash invocation and its expanded prompt — symmetric in order."""

    def test_slash_then_user_slash_pairs(self, ctx: RenderingContext) -> None:
        """`/init` flow: Slash invocation followed by expanded prompt."""
        slash = _slash(ctx, "u1", name="init")
        user_slash = _user_slash(ctx, "u2", text="Please analyze...")

        assert _try_pair_adjacent(slash, user_slash) is True
        assert slash.pair_last == user_slash.message_index
        assert user_slash.pair_first == slash.message_index

    def test_user_slash_then_slash_pairs(self, ctx: RenderingContext) -> None:
        """`/exit` flow: caveat (User slash command) then Slash invocation."""
        caveat = _user_slash(ctx, "v1", text="Caveat: messages below were generated...")
        slash = _slash(ctx, "v2", name="exit")

        assert _try_pair_adjacent(caveat, slash) is True
        assert caveat.pair_last == slash.message_index
        assert slash.pair_first == caveat.message_index

    def test_two_slash_messages_do_not_pair(self, ctx: RenderingContext) -> None:
        """Two adjacent SlashCommand messages are unrelated; no pair."""
        a = _slash(ctx, "a1", name="init")
        b = _slash(ctx, "a2", name="exit")
        assert _try_pair_adjacent(a, b) is False
        assert a.pair_last is None and b.pair_first is None

    def test_two_user_slash_messages_do_not_pair(self, ctx: RenderingContext) -> None:
        a = _user_slash(ctx, "b1", text="one")
        b = _user_slash(ctx, "b2", text="two")
        assert _try_pair_adjacent(a, b) is False


# ----------------------------- regression: existing rules --------------------


class TestExistingPairingRulesPreserved:
    """The new rule must not regress slash-cmd → command-output pairing."""

    def test_slash_then_output_still_pairs(self, ctx: RenderingContext) -> None:
        slash = _slash(ctx, "c1", name="context")
        output = _cmd_output(ctx, "c2", stdout="rendered context")
        assert _try_pair_adjacent(slash, output) is True
        assert slash.pair_last == output.message_index

    def test_user_slash_then_output_still_pairs(self, ctx: RenderingContext) -> None:
        user_slash = _user_slash(ctx, "d1", text="some prompt")
        output = _cmd_output(ctx, "d2", stdout="rendered")
        assert _try_pair_adjacent(user_slash, output) is True
        assert user_slash.pair_last == output.message_index


# ----------------------------- full pass: option A orphan --------------------


class TestThreeMessageSequence:
    """Per option A in the implementation plan: when a 3-msg sequence appears
    (UserSlash caveat → Slash → CommandOutput), the slash-pair wins and the
    trailing CommandOutput renders standalone. Documented trade-off — revisit
    if the orphan output ever looks visually broken."""

    def test_caveat_slash_output_orphans_the_output(
        self, ctx: RenderingContext
    ) -> None:
        caveat = _user_slash(ctx, "e1", text="Caveat: ...")
        slash = _slash(ctx, "e2", name="exit")
        output = _cmd_output(ctx, "e3", stdout="See ya!")

        _identify_message_pairs([caveat, slash, output])

        # Slash-pair wins.
        assert caveat.pair_last == slash.message_index
        assert slash.pair_first == caveat.message_index
        # Output is unpaired (orphan, by design — option A).
        assert output.pair_first is None
        assert output.pair_last is None

    def test_slash_userslash_no_output_pairs_cleanly(
        self, ctx: RenderingContext
    ) -> None:
        """`/init` — no command output — pairs without ambiguity."""
        slash = _slash(ctx, "f1", name="init")
        user_slash = _user_slash(ctx, "f2", text="Please analyze...")

        _identify_message_pairs([slash, user_slash])

        assert slash.pair_last == user_slash.message_index
        assert user_slash.pair_first == slash.message_index
