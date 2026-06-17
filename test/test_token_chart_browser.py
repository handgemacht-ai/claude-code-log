"""Live-browser tests for the token-usage chart overlay (📊).

Follows the ``file://`` rendering pattern in ``test_nested_dom_browser.py``:
render a synthetic transcript to an HTML file and drive it with Playwright.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page

from claude_code_log.converter import load_transcript
from claude_code_log.html.renderer import generate_html


def _user(uuid: str, ts: str, parent: str | None = None) -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "parentUuid": parent,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": "s",
        "version": "1.0.0",
        "uuid": uuid,
        "message": {"role": "user", "content": [{"type": "text", "text": "hi " * 30}]},
    }


def _assistant(
    uuid: str,
    ts: str,
    parent: str,
    request_id: str,
    usage: dict | None,
) -> dict:
    entry: dict = {
        "type": "assistant",
        "timestamp": ts,
        "parentUuid": parent,
        "isSidechain": False,
        "userType": "human",
        "cwd": "/tmp",
        "sessionId": "s",
        "version": "1.0.0",
        "uuid": uuid,
        "requestId": request_id,
        "message": {
            "id": uuid,
            "type": "message",
            "role": "assistant",
            "model": "claude-3",
            "content": [{"type": "text", "text": "answer " * 30}],
        },
    }
    if usage is not None:
        entry["message"]["usage"] = usage
    return entry


def _usage(inp: int, cache_read: int, output: int, cache_write: int) -> dict:
    return {
        "input_tokens": inp,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output,
        "cache_creation_input_tokens": cache_write,
    }


def _render(tmp_path: Path, lines: list[dict], name: str = "tc.html") -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )
    html = generate_html(load_transcript(path))
    out = tmp_path / name
    out.write_text(html, encoding="utf-8")
    return f"file://{out}"


def _tall_transcript(turns: int = 30) -> list[dict]:
    """A tall transcript: every assistant turn carries usage (→ one bar each)."""
    lines: list[dict] = []
    prev: str | None = None
    for i in range(turns):
        u = f"u{i}"
        a = f"a{i}"
        ts_u = f"2025-01-01T10:{i:02d}:00Z"
        ts_a = f"2025-01-01T10:{i:02d}:01Z"
        lines.append(_user(u, ts_u, prev))
        lines.append(
            _assistant(
                a,
                ts_a,
                u,
                f"req{i}",
                _usage(10 + i, 40 + i, 20 + i, 3 + i),
            )
        )
        prev = a
    return lines


class TestTokenChartOverlay:
    @pytest.mark.browser
    def test_open_shows_panel_with_bars(self, page: Page, tmp_path: Path) -> None:
        page.goto(_render(tmp_path, _tall_transcript()))
        page.wait_for_timeout(200)

        # Panel hidden initially.
        assert page.locator("#token-chart-panel").is_hidden()

        page.click("#toggleTokenChart")
        page.wait_for_timeout(200)

        assert page.locator("#token-chart-panel").is_visible()

        result = page.evaluate(
            """() => {
                const data = JSON.parse(
                    document.getElementById('token-chart-data').textContent);
                const bars = document.querySelectorAll('#token-chart-svg .token-bar');
                const rects = document.querySelectorAll('#token-chart-svg .token-bar rect');
                return {
                    entries: data.length,
                    bars: bars.length,
                    rects: rects.length,
                };
            }"""
        )
        assert result["entries"] == 30
        # One bar per response.
        assert result["bars"] == 30
        # Every segment here is non-zero → 4 rects per bar.
        assert result["rects"] == 30 * 4

    @pytest.mark.browser
    def test_click_bar_scrolls_and_flashes(self, page: Page, tmp_path: Path) -> None:
        page.goto(_render(tmp_path, _tall_transcript()))
        page.wait_for_timeout(200)
        page.click("#toggleTokenChart")
        page.wait_for_timeout(200)

        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(100)
        start_scroll = page.evaluate("window.scrollY")

        # Click the LAST bar → its message is near the page bottom.
        target_id = page.evaluate(
            """() => {
                const bars = document.querySelectorAll('#token-chart-svg .token-bar');
                const last = bars[bars.length - 1];
                last.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                return last.getAttribute('data-message-id');
            }"""
        )
        page.wait_for_timeout(900)

        end_scroll = page.evaluate("window.scrollY")
        assert end_scroll > start_scroll, (start_scroll, end_scroll)

        # Target flashed with the highlight color.
        flashed = page.evaluate(
            f"""() => {{
                const el = document.getElementById('msg-{target_id}');
                return el ? el.style.backgroundColor : null;
            }}"""
        )
        assert flashed == "rgb(255, 243, 205)"  # #fff3cd

        # Highlight clears after ~2s.
        page.wait_for_timeout(2200)
        cleared = page.evaluate(
            f"""() => {{
                const el = document.getElementById('msg-{target_id}');
                return el ? el.style.backgroundColor : null;
            }}"""
        )
        assert cleared == ""

    @pytest.mark.browser
    def test_log_scale_toggle_rerenders(self, page: Page, tmp_path: Path) -> None:
        page.goto(_render(tmp_path, _tall_transcript()))
        page.wait_for_timeout(200)
        page.click("#toggleTokenChart")
        page.wait_for_timeout(200)

        before = page.evaluate(
            """() => {
                const r = document.querySelector('#token-chart-svg .token-bar rect');
                return r ? r.getAttribute('height') : null;
            }"""
        )
        # Switch to log scale.
        page.click('.token-chart-scale-toggle button[data-scale="log"]')
        page.wait_for_timeout(150)

        state = page.evaluate(
            """() => {
                const logBtn = document.querySelector(
                    '.token-chart-scale-toggle button[data-scale="log"]');
                const r = document.querySelector('#token-chart-svg .token-bar rect');
                return {
                    logActive: logBtn.classList.contains('active'),
                    height: r ? r.getAttribute('height') : null,
                };
            }"""
        )
        assert state["logActive"] is True
        # The re-render changed the bar geometry (log compresses differently).
        assert state["height"] != before

    @pytest.mark.browser
    def test_empty_state(self, page: Page, tmp_path: Path) -> None:
        # A transcript whose assistant turn carries no usage → empty island.
        lines = [
            _user("u0", "2025-01-01T10:00:00Z"),
            _assistant("a0", "2025-01-01T10:00:01Z", "u0", "req0", None),
        ]
        page.goto(_render(tmp_path, lines, name="empty.html"))
        page.wait_for_timeout(200)
        page.click("#toggleTokenChart")
        page.wait_for_timeout(200)

        result = page.evaluate(
            """() => {
                const empty = document.querySelector('.token-chart-empty');
                const svg = document.getElementById('token-chart-svg');
                const data = JSON.parse(
                    document.getElementById('token-chart-data').textContent);
                return {
                    entries: data.length,
                    emptyVisible: empty && getComputedStyle(empty).display !== 'none',
                    svgHidden: svg && getComputedStyle(svg).display === 'none',
                };
            }"""
        )
        assert result["entries"] == 0
        assert result["emptyVisible"] is True
        assert result["svgHidden"] is True
