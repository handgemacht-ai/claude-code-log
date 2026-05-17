"""Cross-link from TaskOutput / TaskUpdate headers back to the spawn
that minted their task_id (#154).

Three flows share one rendering pass (``_link_task_id_consumers``):

1. ``TaskOutput`` polling a ``run_in_background`` Bash — id sourced
   from ``toolUseResult.backgroundTaskId``.
2. ``TaskOutput`` polling an async-agent ``Task`` — id sourced from
   the launch confirmation (``agentId`` in the toolUseResult, or
   recovered via ``_async_agent_id_from_tool_result``).
3. ``TaskUpdate`` referring back to a ``TaskCreate`` by the
   backend-assigned ``#N`` id.

Each consumer's header wraps ``#<id>`` in ``<a class='task-id-backlink'
href='#msg-d-N'>``, where ``msg-d-N`` is the originating tool_use card.

The fixture (``test_data/task_id_linking.jsonl``) lays the spawns out
before the polls so the pass can resolve every id; ordering matches
the natural transcript shape.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_log.converter import load_transcript
from claude_code_log.factories.tool_factory import parse_bash_output
from claude_code_log.html.renderer import HtmlRenderer
from claude_code_log.markdown.renderer import MarkdownRenderer
from claude_code_log.models import (
    BashOutput,
    ToolResultContent,
)


FIXTURE = Path(__file__).parent / "test_data" / "task_id_linking.jsonl"
CROSS_SESSION_FIXTURE = (
    Path(__file__).parent / "test_data" / "task_id_linking_cross_session.jsonl"
)


# -----------------------------------------------------------------------------
# Parser unit test — ``BashOutput.background_task_id`` is sourced from the
# structured ``toolUseResult.backgroundTaskId`` field, not text parsing.
# -----------------------------------------------------------------------------


class TestBashBackgroundTaskIdParse:
    def test_background_task_id_from_structured_field(self) -> None:
        result = ToolResultContent(
            type="tool_result",
            tool_use_id="x",
            content="Command running in background with ID: b1bg01",
        )
        out = parse_bash_output(
            result,
            None,
            tool_use_result={
                "stdout": "",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
                "backgroundTaskId": "b1bg01",
            },
        )
        assert isinstance(out, BashOutput)
        assert out.background_task_id == "b1bg01"

    def test_no_tool_use_result_means_no_id(self) -> None:
        """Foreground Bash calls have no ``toolUseResult`` field — id
        must stay None so the cross-link pass can't false-positive.
        """
        result = ToolResultContent(
            type="tool_result", tool_use_id="x", content="hello\n"
        )
        out = parse_bash_output(result, None, tool_use_result=None)
        assert isinstance(out, BashOutput)
        assert out.background_task_id is None

    def test_missing_background_task_id_key(self) -> None:
        """Foreground-style ``toolUseResult`` (stdout/stderr only) →
        no id leak.
        """
        result = ToolResultContent(
            type="tool_result", tool_use_id="x", content="hello\n"
        )
        out = parse_bash_output(
            result,
            None,
            tool_use_result={"stdout": "hello", "stderr": "", "interrupted": False},
        )
        assert isinstance(out, BashOutput)
        assert out.background_task_id is None


# -----------------------------------------------------------------------------
# End-to-end fixture tests
# -----------------------------------------------------------------------------


@pytest.mark.usefixtures("_ensure_fixture_present")
class TestTaskIdLinkingFixture:
    """Drive the real renderers against ``test_data/task_id_linking.jsonl``.

    The fixture sequences a Bash run_in_background, an async-agent
    Task, and a TaskCreate before three matching consumers
    (TaskOutput x2, TaskUpdate); one render exercises all three
    backlink paths.
    """

    @staticmethod
    def _html() -> str:
        return HtmlRenderer().generate(load_transcript(FIXTURE), "Test")

    @staticmethod
    def _md() -> str:
        return MarkdownRenderer().generate(load_transcript(FIXTURE), "Test")

    @staticmethod
    def _spawn_anchor(html: str, tool_use_id: str) -> str:
        """Find the ``msg-d-N`` id of the tool_use div carrying
        ``tool_use_id`` in its title-tooltip (the renderer surfaces
        the API id as ``title="ID: toolu_..."`` on the header span).
        Anchoring on the tool_use_id keeps the test stable across
        renumbering of message indices.
        """
        match = re.search(
            r"id='(msg-d-\d+)'>"
            r"(?:(?!</div>).)*?"
            r'title="ID: ' + re.escape(tool_use_id) + r'"',
            html,
            re.DOTALL,
        )
        assert match, f"tool_use div for {tool_use_id} not found"
        return match.group(1)

    def test_taskoutput_local_bash_links_to_bash_call(self) -> None:
        """``TaskOutput #b1bg01`` (local_bash) → anchor to the Bash
        run_in_background call card.
        """
        html = self._html()
        bash_anchor = self._spawn_anchor(html, "toolu_154_bash_bg")
        link_re = re.compile(
            r"<a class='task-id-backlink' href='#(msg-d-\d+)'>"
            r"<code>#b1bg01</code></a>"
        )
        match = link_re.search(html)
        assert match, "TaskOutput #b1bg01 backlink not found"
        assert match.group(1) == bash_anchor

    def test_taskoutput_local_agent_links_to_task_call(self) -> None:
        """``TaskOutput #a1agnt`` (local_agent) → anchor to the async
        Task launch card.
        """
        html = self._html()
        task_anchor = self._spawn_anchor(html, "toolu_154_task_async")
        link_re = re.compile(
            r"<a class='task-id-backlink' href='#(msg-d-\d+)'>"
            r"<code>#a1agnt</code></a>"
        )
        match = link_re.search(html)
        assert match, "TaskOutput #a1agnt backlink not found"
        assert match.group(1) == task_anchor

    def test_taskupdate_links_to_taskcreate_call(self) -> None:
        """``TaskUpdate #1`` → anchor to the originating TaskCreate
        card.
        """
        html = self._html()
        tc_anchor = self._spawn_anchor(html, "toolu_154_tc_1")
        link_re = re.compile(
            r"<a class='task-id-backlink' href='#(msg-d-\d+)'>"
            r"<code>#1</code></a>"
        )
        match = link_re.search(html)
        assert match, "TaskUpdate #1 backlink not found"
        assert match.group(1) == tc_anchor

    def test_backlink_css_rule_present(self) -> None:
        """The dotted-underline visual affordance ships with the
        bundled CSS (regression for accidental rule drops). Both
        backlink and forward-link rules must be present (PR #158
        follow-up split the two directions into distinct classes).
        """
        html = self._html()
        assert ".task-id-backlink" in html
        assert ".task-id-forward-link" in html

    def test_bash_spawn_title_has_async_hint_with_minted_id(self) -> None:
        """The ``Bash`` ``run_in_background`` spawn card surfaces
        ``[async #b1bg01]`` in its title (PR #158 follow-up — was
        previously plain ``💻 Bash <desc>`` with the id buried in the
        result body).

        Locating the spawn card by tool_use_id keeps the assertion
        stable across renumbering. The minted ``#<id>`` lives inside
        the dedicated ``task-async-hint`` span so the CSS class
        scoping is preserved.
        """
        html = self._html()
        bash_anchor = self._spawn_anchor(html, "toolu_154_bash_bg")
        # Extract the spawn card's title region: starts at the anchor's
        # opening, ends at the first </div> of the message header.
        card_re = re.compile(
            r"id='" + re.escape(bash_anchor) + r"'>(.+?)</div>",
            re.DOTALL,
        )
        card = card_re.search(html)
        assert card, f"spawn card {bash_anchor} not found"
        assert "[async " in card.group(1)
        assert "#b1bg01" in card.group(1)
        assert "task-async-hint" in card.group(1)

    def test_bash_spawn_title_forward_links_to_first_taskoutput(self) -> None:
        """The Bash spawn's ``#b1bg01`` is a forward-link anchor
        pointing at the first ``TaskOutput`` poll for that id
        (PR #158 follow-up). Complements the backlink direction from
        #154 — readers can now navigate both ways.
        """
        html = self._html()
        bash_anchor = self._spawn_anchor(html, "toolu_154_bash_bg")
        # The first TaskOutput poll for b1bg01 is the one with
        # tool_use_id toolu_154_to_bash (fixture sequencing).
        consumer_anchor = self._spawn_anchor(html, "toolu_154_to_bash")
        # Match the forward-link anchor specifically (distinct class
        # from the backlink — they'd collide on the bare #b1bg01).
        forward_re = re.compile(
            r"<a class='task-id-forward-link' href='#(msg-d-\d+)'>"
            r"<code>#b1bg01</code></a>"
        )
        # Search within the spawn card's region to make sure we're
        # matching the forward link emitted on the SPAWN, not on the
        # consumer card (which would be a backlink anyway, different
        # class — defensive scoping).
        card_re = re.compile(
            r"id='" + re.escape(bash_anchor) + r"'>(.+?)</div>",
            re.DOTALL,
        )
        card_match = card_re.search(html)
        assert card_match
        forward_match = forward_re.search(card_match.group(1))
        assert forward_match, (
            "expected forward-link on Bash spawn card pointing at "
            f"first TaskOutput poll (consumer_anchor={consumer_anchor})"
        )
        assert forward_match.group(1) == consumer_anchor

    def test_task_async_spawn_title_forward_links_to_first_taskoutput(
        self,
    ) -> None:
        """Mirror of the Bash case for the async-agent ``Task`` spawn:
        ``#a1agnt`` on the spawn card forward-links to the first
        ``TaskOutput`` poll for that agent.
        """
        html = self._html()
        task_anchor = self._spawn_anchor(html, "toolu_154_task_async")
        consumer_anchor = self._spawn_anchor(html, "toolu_154_to_agent")
        card_re = re.compile(
            r"id='" + re.escape(task_anchor) + r"'>(.+?)</div>",
            re.DOTALL,
        )
        card_match = card_re.search(html)
        assert card_match
        forward_re = re.compile(
            r"<a class='task-id-forward-link' href='#(msg-d-\d+)'>"
            r"<code>#a1agnt</code></a>"
        )
        forward_match = forward_re.search(card_match.group(1))
        assert forward_match, "expected forward-link on async Task spawn card"
        assert forward_match.group(1) == consumer_anchor

    def test_markdown_spawn_titles_have_async_hint_with_id(self) -> None:
        """Markdown spawn titles carry ``[async #<id>]`` once the
        matching tool_result has been parsed. No clickable anchor —
        backlinks and forward-links are HTML-only (per the #154
        convention) — but the plain ``#<id>`` is still greppable.
        """
        md = self._md()
        # Bash spawn — minted background_task_id is b1bg01.
        assert "[async `#b1bg01`]" in md
        # Async Task spawn — minted agent_id is a1agnt.
        assert "[async `#a1agnt`]" in md

    def test_cross_session_no_mislink_on_shared_todo_id(self) -> None:
        """Two sessions each minting ``TaskCreate #1`` and then
        ``TaskUpdate #1`` must NOT cross-link: each update's backlink
        targets the TaskCreate in its OWN session. Regression for
        CodeRabbit #158: id-only keys would have collapsed both ``#1``
        ids onto whichever TaskCreate was indexed first.
        """
        if not CROSS_SESSION_FIXTURE.exists():
            pytest.fail(f"Required fixture missing: {CROSS_SESSION_FIXTURE}")
        html = HtmlRenderer().generate(load_transcript(CROSS_SESSION_FIXTURE), "Test")

        # Locate both TaskCreate spawn anchors and both TaskUpdate
        # consumers; ``_spawn_anchor`` keys off tool_use_id so it
        # disambiguates session A vs B unambiguously.
        sA_tc = self._spawn_anchor(html, "toolu_sA_tc")
        sB_tc = self._spawn_anchor(html, "toolu_sB_tc")
        sA_tu = self._spawn_anchor(html, "toolu_sA_tu")
        sB_tu = self._spawn_anchor(html, "toolu_sB_tu")
        # Sanity — the four spawn ids must all be distinct.
        assert len({sA_tc, sB_tc, sA_tu, sB_tu}) == 4

        # Find both ``#1`` backlinks. Order matches document order so
        # session A appears before session B.
        backlinks = re.findall(
            r"<a class='task-id-backlink' href='#(msg-d-\d+)'><code>#1</code></a>",
            html,
        )
        # We expect exactly two backlinks (one per TaskUpdate). If the
        # bug regressed (id-only keys), both would point at sA_tc.
        assert len(backlinks) == 2, (
            f"Expected exactly two ``#1`` backlinks, got {len(backlinks)}"
        )
        assert backlinks[0] == sA_tc, (
            "Session A's TaskUpdate #1 should backlink to session A's TaskCreate "
            f"({sA_tc}), got {backlinks[0]}"
        )
        assert backlinks[1] == sB_tc, (
            "Session B's TaskUpdate #1 should backlink to session B's TaskCreate "
            f"({sB_tc}), got {backlinks[1]} — would have been {sA_tc} under "
            "the id-only-keyed regression"
        )

    def test_markdown_titles_have_plain_id_no_anchor(self) -> None:
        """Markdown only renders session-level anchors; message-level
        backlinks are HTML-only. The titles still carry the plain
        ``#<id>`` form so the reader can grep across the document.
        """
        md = self._md()
        # TaskOutput titles surface the polled id verbatim (inline code).
        assert "🔍 TaskOutput `#b1bg01`" in md
        assert "🔍 TaskOutput `#a1agnt`" in md
        # TaskUpdate's id rides on the standard ``#N <subject> [updated]``
        # title shape; assert the id is present (subject may or may not
        # be resolved depending on the markdown renderer's lookup map).
        assert "#1" in md
        # No HTML anchor leakage into the markdown stream.
        assert "task-id-backlink" not in md


# -----------------------------------------------------------------------------
# Module-level fixture (skip end-to-end tests when JSONL is missing)
# -----------------------------------------------------------------------------


@pytest.fixture(scope="class")
def _ensure_fixture_present() -> None:  # pyright: ignore[reportUnusedFunction]
    """Fail loudly when the JSONL fixture is missing — silent skip
    would mask a fixture-deletion regression (CodeRabbit #158).
    Class-scoped + opt-in via ``@pytest.mark.usefixtures`` so parser
    unit tests still run independent of the fixture.
    """
    if not FIXTURE.exists():
        pytest.fail(f"Required fixture missing: {FIXTURE}")
