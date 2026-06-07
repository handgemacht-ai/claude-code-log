"""Tests for Workflow tool-input + async-result-body rendering (#174 PR2).

D3: a ``Workflow`` tool_use renders a meta header (name/description/phase
pills) above its JavaScript orchestrator, syntax-highlighted — not the raw
ToolUseContent fallback.
D4: a JSON-shaped async-result body is pretty-printed + highlighted as JSON;
non-JSON (markdown) bodies fall back to the existing markdown rendering.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_log.converter import load_transcript
from claude_code_log.html.renderer import generate_html
from claude_code_log.html.utils import render_async_result_body
from claude_code_log.markdown.renderer import MarkdownRenderer
from claude_code_log.workflow import parse_workflow_meta

TRUNK = (
    Path(__file__).parent
    / "test_data"
    / "workflow_basic"
    / "11110000-0000-4000-8000-000000000001.jsonl"
)


class TestWorkflowToolInputRendering:
    """D3 — Workflow tool_use → meta header + highlighted JS."""

    def _html(self) -> str:
        return generate_html(load_transcript(TRUNK))

    def test_meta_header_from_script_meta_block(self) -> None:
        html = self._html()
        assert "workflow-meta" in html
        assert "workflow-name" in html and "demo-review" in html
        # description surfaced from the script's meta block
        assert "Review changed files across dimensions" in html

    def test_both_phase_pills_rendered(self) -> None:
        html = self._html()
        assert html.count("workflow-phase-pill") >= 2  # Map + Synthesize

    def test_script_highlighted_as_javascript(self) -> None:
        html = self._html()
        # Target the rendered div, not the `.workflow-script` CSS rule in <head>.
        idx = html.find("class='workflow-script'")
        assert idx != -1, "expected a rendered workflow-script block"
        segment = html[idx : idx + 600]
        # render_file_content_collapsible emits a Pygments highlight table
        assert "highlight" in segment

    def test_specialized_path_not_raw_fallback(self) -> None:
        # The generic fallback would dump input as a params table / raw JSON
        # with no meta header or highlighted script; the specialized renderer
        # produces both.
        html = self._html()
        assert "workflow-meta" in html and "workflow-script" in html


class TestAsyncResultBodyJson:
    """D4 — JSON-aware async-result body rendering."""

    def test_json_body_pretty_printed_and_highlighted(self) -> None:
        out = render_async_result_body(
            '{"plan": "Land parsing first.", "areaCount": 2}', "task-async-answer"
        )
        assert "highlight" in out  # Pygments-highlighted
        assert "task-async-answer" in out  # wrapper css class preserved
        assert out.count("\n") > 2  # pretty-printed (indented, multi-line)

    def test_truncated_json_highlights_without_crashing(self) -> None:
        # Real async previews are often truncated mid-value; still starts with
        # {" so it's treated as JSON and highlighted best-effort.
        out = render_async_result_body('{"plan": "Lan', "x")
        assert "highlight" in out

    def test_markdown_body_uses_markdown_path(self) -> None:
        out = render_async_result_body("## Plan\n\nLand it first.", "x")
        # markdown path → no Pygments code-highlight table
        assert 'class="highlight"' not in out
        assert "Plan" in out

    def test_non_json_brace_text_is_not_treated_as_json(self) -> None:
        # Heuristic is specifically `{"` — a lone "{" (e.g. prose) is markdown.
        out = render_async_result_body("{ not really json", "x")
        assert 'class="highlight"' not in out


class TestWorkflowToolInputMarkdown:
    """D3 parity for the Markdown renderer — registering Workflow in
    TOOL_INPUT_MODELS is format-neutral, so the script must NOT vanish from
    Markdown output (regression guard, monk PR2 review)."""

    def _md(self) -> str:
        return MarkdownRenderer().generate(load_transcript(TRUNK))

    def test_script_present_in_markdown(self) -> None:
        md = self._md()
        # The script body (and its meta) must render, not disappear.
        assert "demo-review" in md
        assert "export const meta" in md
        assert "```js" in md  # fenced as JavaScript

    def test_meta_header_in_markdown(self) -> None:
        md = self._md()
        assert "Review changed files across dimensions" in md  # description
        assert "Map" in md and "Synthesize" in md  # phase titles


class TestWorkflowMetaParsing:
    """Unit tests for the shared meta parser (issue #174)."""

    def test_name_description_phases(self) -> None:
        script = (
            "export const meta = {\n"
            "  name: 'demo',\n"
            "  description: 'A demo',\n"
            "  phases: [{ title: 'Map' }, { title: 'Synthesize' }],\n"
            "}\n"
        )
        assert parse_workflow_meta(script) == ("demo", "A demo", ["Map", "Synthesize"])

    def test_bracket_in_phase_detail_does_not_truncate_phases(self) -> None:
        # N1 regression: a ']' inside a phase detail must not cut the list short.
        script = (
            "export const meta = {\n"
            "  phases: [{ title: 'Scan', detail: 'grep [logs]' }, { title: 'Fix' }],\n"
            "}\n"
        )
        assert parse_workflow_meta(script)[2] == ["Scan", "Fix"]

    def test_no_meta_block_returns_empty(self) -> None:
        assert parse_workflow_meta("const x = 1\nawait agent('hi')\n") == ("", "", [])


_JS_META = (
    "export const meta = {\n"
    "  name: 'js-name',\n"
    "  description: 'js-desc',\n"
    "  phases: [{ title: 'Map' }],\n"
    "}\n"
)


class TestSnapshotFirstHeader:
    """PR3 / cboos refinement: the header prefers the authoritative
    <runId>.json snapshot over the best-effort JS-meta regex, warns on JS-meta
    drift, and falls back to the regex for a running (no-snapshot) workflow."""

    def _run(self, **kw):
        from claude_code_log.workflow import WorkflowPhase, WorkflowRun

        return WorkflowRun(
            run_id="r",
            workflow_name=kw.get("name", "SNAP-NAME"),
            has_snapshot=kw.get("has_snapshot", True),
            phases=kw.get(
                "phases",
                [
                    WorkflowPhase(index=0, title="Alpha"),
                    WorkflowPhase(index=1, title="Beta"),
                ],
            ),
        )

    def test_snapshot_name_and_phases_win_description_from_js(self) -> None:
        from claude_code_log.workflow import resolve_workflow_header

        name, desc, phases = resolve_workflow_header(self._run(), _JS_META)
        assert name == "SNAP-NAME"  # snapshot workflowName wins over JS name
        assert phases == ["Alpha", "Beta"]  # snapshot phases win over JS phases
        assert desc == "js-desc"  # description has no snapshot source → JS

    def test_no_snapshot_falls_back_to_js(self) -> None:
        from claude_code_log.workflow import resolve_workflow_header

        assert resolve_workflow_header(None, _JS_META) == (
            "js-name",
            "js-desc",
            ["Map"],
        )

    def test_drift_warning_when_js_meta_misses(self, caplog) -> None:
        import logging

        from claude_code_log.workflow import resolve_workflow_header

        with caplog.at_level(logging.WARNING, logger="claude_code_log.workflow"):
            # snapshot has name+phases, but the script has no `export const meta`
            resolve_workflow_header(self._run(), "const x = 1\n")
        assert any("may have drifted" in r.message for r in caplog.records)


class TestWorkflowRunLinkage:
    """PR3 step 1-2: a parsed run links to its Workflow tool_use by taskId on a
    directory load, so the formatter can render snapshot-first."""

    def test_run_links_to_tool_use_input(self) -> None:
        from claude_code_log.converter import load_directory_transcripts
        from claude_code_log.models import ToolUseMessage, WorkflowToolInput
        from claude_code_log.renderer import generate_template_messages

        msgs, tree = load_directory_transcripts(TRUNK.parent, silent=True)
        assert "wf_demo01" in tree.workflow_runs
        _roots, _nav, ctx = generate_template_messages(msgs, session_tree=tree)
        linked = [
            tm.content.input.workflow_run
            for tm in ctx.messages
            if tm is not None
            and isinstance(tm.content, ToolUseMessage)
            and tm.content.tool_name == "Workflow"
            and isinstance(tm.content.input, WorkflowToolInput)
        ]
        assert len(linked) == 1
        assert linked[0] is not None
        assert linked[0].run_id == "wf_demo01"

    def test_decoy_local_meta_ignored_for_exported_block(self) -> None:
        # CR #205: only the EXPORTED `meta` declaration is the header source;
        # a non-export local `meta = {...}` before it must not be mis-parsed.
        script = (
            "const meta = { name: 'DECOY', description: 'local' }\n"
            "export const meta = {\n"
            "  name: 'real-wf',\n"
            "  description: 'the real one',\n"
            "  phases: [{ title: 'Map' }],\n"
            "}\n"
        )
        assert parse_workflow_meta(script) == ("real-wf", "the real one", ["Map"])


class TestWorkflowMarkdownEscaping:
    """CR #205 (Major): script-derived meta fields must be HTML-tag-neutralized
    before injection into the Markdown header (the script body itself is fenced
    and safe)."""

    def test_header_neutralizes_html_tags(self) -> None:
        from claude_code_log.models import WorkflowToolInput

        script = (
            "export const meta = {\n"
            "  name: 'pwn <script>alert(1)</script>',\n"
            "  description: 'd <img src=x onerror=alert(2)>',\n"
            "  phases: [{ title: 'P <b>x</b>' }],\n"
            "}\n"
        )
        out = MarkdownRenderer().format_WorkflowToolInput(
            WorkflowToolInput(script=script),
            None,  # type: ignore[arg-type]  # message is unused by this formatter
        )
        # Inspect only the header (everything before the fenced script, where
        # the raw tags legitimately appear inside a code block).
        header = out.split("```")[0]
        assert "<script>" not in header
        assert "<img" not in header
        assert "<b>" not in header
        # Neutralized text still readable in the header.
        assert "alert(1)" in header
