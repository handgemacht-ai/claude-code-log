"""Test cases for ScheduleWakeup + Cron* tool rendering (#148).

Five concerns:

1. Input/output factories — typed models from raw tool_use /
   tool_result entries; output parsers extract the structured
   fields when the format matches and fall back to raw text
   otherwise.
2. HTML rendering — title carries the right summary per tool;
   body grids, collapsible prompts, and structured cron-list
   tables match the spec.
3. Markdown rendering — title format mirrors the HTML title's
   summary; body uses fenced prompts via the adaptive
   ``_code_fence`` helper.
4. End-to-end fixture — drives the full pipeline against a
   single JSONL with one call per tool in the family.
5. CronList output parser robustness — the harness's exact
   format isn't guaranteed, so the parser must fall back
   gracefully when the row regex doesn't match.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_log.converter import load_transcript
from claude_code_log.factories.tool_factory import (
    parse_croncreate_output,
    parse_crondelete_output,
    parse_cronlist_output,
    parse_schedulewakeup_output,
)
from claude_code_log.html.renderer import HtmlRenderer
from claude_code_log.html.tool_formatters import (
    format_croncreate_input,
    format_cronlist_output,
    format_schedulewakeup_input,
)
from claude_code_log.markdown.renderer import MarkdownRenderer
from claude_code_log.models import (
    CronCreateInput,
    CronCreateOutput,
    CronDeleteInput,
    CronDeleteOutput,
    CronListInput,
    CronListItem,
    CronListOutput,
    ScheduleWakeupInput,
    ScheduleWakeupOutput,
    ToolResultContent,
)


FIXTURE = Path(__file__).parent / "test_data" / "cron_tools.jsonl"


# -----------------------------------------------------------------------------
# Input model tests
# -----------------------------------------------------------------------------


class TestSchedulingInputModels:
    def test_schedulewakeup_required_fields(self) -> None:
        m = ScheduleWakeupInput(
            delaySeconds=60, reason="check build", prompt="/loop foo"
        )
        assert m.delaySeconds == 60
        assert m.reason == "check build"
        assert m.prompt == "/loop foo"

    def test_croncreate_optional_flags_default_none(self) -> None:
        m = CronCreateInput(cron="0 9 * * *", prompt="/morning")
        assert m.recurring is None
        assert m.durable is None

    def test_cronlist_takes_no_inputs(self) -> None:
        # Tolerates the empty input dict the harness sends.
        m = CronListInput()
        assert m is not None

    def test_crondelete_requires_id(self) -> None:
        m = CronDeleteInput(id="cj_abc")
        assert m.id == "cj_abc"


# -----------------------------------------------------------------------------
# Output parser tests
# -----------------------------------------------------------------------------


def _result(text: str) -> ToolResultContent:
    return ToolResultContent(type="tool_result", tool_use_id="x", content=text)


class TestSchedulingOutputParsers:
    def test_schedulewakeup_parses_clock_and_delay(self) -> None:
        out = parse_schedulewakeup_output(
            _result("Next wakeup scheduled for 10:04:00 (in 240s)."), None
        )
        assert isinstance(out, ScheduleWakeupOutput)
        assert out.next_at == "10:04:00"
        assert out.in_seconds == 240
        assert "Next wakeup scheduled" in out.text

    def test_schedulewakeup_falls_back_to_text(self) -> None:
        out = parse_schedulewakeup_output(_result("Some other message."), None)
        assert out is not None
        assert out.next_at is None
        assert out.in_seconds is None
        assert out.text == "Some other message."

    def test_schedulewakeup_empty_returns_none(self) -> None:
        assert parse_schedulewakeup_output(_result(""), None) is None

    def test_croncreate_extracts_job_id(self) -> None:
        out = parse_croncreate_output(
            _result("Scheduled cron job cj_abc-123. Will fire daily."), None
        )
        assert isinstance(out, CronCreateOutput)
        assert out.job_id == "cj_abc-123"

    def test_croncreate_falls_back_when_format_unknown(self) -> None:
        out = parse_croncreate_output(_result("OK."), None)
        assert out is not None
        assert out.job_id is None
        assert out.text == "OK."

    def test_cronlist_parses_structured_rows(self) -> None:
        text = (
            "Active cron jobs:\n"
            "- cj_abc: 57 8 * * * => /morning [recurring]\n"
            "- cj_def: */30 * * * * => /ping [recurring, durable]"
        )
        out = parse_cronlist_output(_result(text), None)
        assert isinstance(out, CronListOutput)
        assert len(out.jobs) == 2
        assert out.jobs[0].id == "cj_abc"
        assert out.jobs[0].cron == "57 8 * * *"
        assert out.jobs[0].prompt == "/morning"
        assert out.jobs[0].recurring is True
        assert out.jobs[0].durable is None
        assert out.jobs[1].durable is True

    def test_cronlist_falls_back_on_unrecognised_format(self) -> None:
        out = parse_cronlist_output(
            _result("Just a free-form summary, no rows here."), None
        )
        assert out is not None
        assert out.jobs == []
        assert "free-form summary" in out.text

    def test_crondelete_captures_text(self) -> None:
        out = parse_crondelete_output(_result("Deleted cron job cj_abc."), None)
        assert isinstance(out, CronDeleteOutput)
        assert "Deleted" in out.text


# -----------------------------------------------------------------------------
# HTML formatter unit tests
# -----------------------------------------------------------------------------


class TestSchedulingHtmlFormatters:
    def test_schedulewakeup_grid_includes_all_three_fields(self) -> None:
        m = ScheduleWakeupInput(
            delaySeconds=300, reason="watch deploy", prompt="/loop bar"
        )
        html = format_schedulewakeup_input(m)
        for key in ("delaySeconds", "reason", "prompt"):
            assert key in html
        assert "300" in html
        assert "watch deploy" in html
        assert "/loop bar" in html

    def test_schedulewakeup_long_prompt_collapses(self) -> None:
        prompt = "\n".join(f"line {i}" for i in range(20))
        m = ScheduleWakeupInput(delaySeconds=60, reason="r", prompt=prompt)
        html = format_schedulewakeup_input(m)
        assert "collapsible-code" in html
        assert "20 lines" in html

    def test_croncreate_omits_optional_flags_when_none(self) -> None:
        m = CronCreateInput(cron="0 * * * *", prompt="/hourly")
        html = format_croncreate_input(m)
        assert "cron" in html
        assert "0 * * * *" in html
        # Optional flags absent.
        assert "recurring" not in html
        assert "durable" not in html

    def test_croncreate_includes_explicit_flags(self) -> None:
        m = CronCreateInput(
            cron="0 9 * * *", prompt="/morning", recurring=True, durable=True
        )
        html = format_croncreate_input(m)
        assert "recurring" in html
        assert "durable" in html

    def test_cronlist_structured_jobs_render_as_table(self) -> None:
        out = CronListOutput(
            text="raw",
            jobs=[
                CronListItem(id="cj_a", cron="0 * * * *", prompt="/a"),
                CronListItem(id="cj_b", cron="*/5 * * * *", prompt="/b"),
            ],
        )
        html = format_cronlist_output(out)
        assert "<table class='cronlist-output-table'>" in html
        assert "cj_a" in html
        assert "0 * * * *" in html
        assert "/b" in html

    def test_cronlist_falls_back_to_raw_text_when_no_jobs(self) -> None:
        out = CronListOutput(text="No jobs scheduled.", jobs=[])
        html = format_cronlist_output(out)
        # Plain <pre> with the raw text, no table chrome.
        assert "<pre class='cronlist-output'>" in html
        assert "No jobs scheduled." in html
        assert "<table" not in html


# -----------------------------------------------------------------------------
# End-to-end fixture tests
# -----------------------------------------------------------------------------


@pytest.mark.usefixtures("_ensure_fixture_present")
class TestSchedulingFixtureRendering:
    """Drive the real renderers against ``test_data/cron_tools.jsonl``.

    The fixture has one call per tool in the family
    (ScheduleWakeup → CronCreate → CronList → CronDelete) so a single
    render exercises all four paths.
    """

    @staticmethod
    def _html() -> str:
        return HtmlRenderer().generate(load_transcript(FIXTURE), "Test")

    @staticmethod
    def _md() -> str:
        return MarkdownRenderer().generate(load_transcript(FIXTURE), "Test")

    def test_html_titles_present_for_all_four_tools(self) -> None:
        html = self._html()
        # Alarm-clock icon for the family + tool-specific summary.
        assert "⏰" in html
        # ScheduleWakeup title carries the +<delay>s shape.
        assert "+240s" in html
        # CronCreate title carries the cron expression.
        assert "57 8 * * *" in html
        # CronList renders the static title literal.
        assert "CronList" in html
        # CronDelete title carries the id.
        assert "cj_def456" in html

    def test_html_schedulewakeup_grid_present(self) -> None:
        html = self._html()
        for key in ("delaySeconds", "reason", "prompt"):
            assert key in html
        # Result paragraph rendered verbatim.
        assert "Next wakeup scheduled for 10:04:00" in html

    def test_html_cronlist_renders_structured_table(self) -> None:
        html = self._html()
        # Both jobs surfaced in the rendered table.
        assert "cj_abc123" in html
        assert "cj_def456" in html
        # Cron expressions visible.
        assert "57 8 * * *" in html
        assert "*/30 * * * *" in html

    def test_html_crondelete_result_paragraph(self) -> None:
        html = self._html()
        assert "Deleted cron job cj_def456" in html

    def test_markdown_titles_use_inline_code_for_values(self) -> None:
        md = self._md()
        # Reason wrapped in inline code (markdown escape via _inline_code).
        assert (
            "⏰ ScheduleWakeup +240s — `First parent loop tick at +4min — by then alice should have committed iter 1.`"
            in md
        )
        # Cron expression wrapped in inline code.
        assert "⏰ CronCreate `57 8 * * *`" in md
        # CronDelete id wrapped in inline code.
        assert "⏰ CronDelete `cj_def456`" in md

    def test_markdown_schedulewakeup_prompt_in_fenced_block(self) -> None:
        md = self._md()
        assert "**delaySeconds:** 240" in md
        # Prompt block opens a fenced code region.
        assert "**prompt:**" in md
        assert "```" in md


# -----------------------------------------------------------------------------
# Module-level fixture (skip end-to-end tests when JSONL is missing)
# -----------------------------------------------------------------------------


@pytest.fixture(scope="class")
def _ensure_fixture_present() -> None:  # pyright: ignore[reportUnusedFunction]
    """Skip the end-to-end fixture-driven tests when the JSONL fixture
    is missing. Class-scoped + opt-in via ``@pytest.mark.usefixtures``
    so model / parser / formatter unit tests still run when the fixture
    file is absent.
    """
    if not FIXTURE.exists():
        pytest.skip(f"Fixture missing: {FIXTURE}")
