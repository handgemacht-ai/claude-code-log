"""mistune inline-parser plugins shared between the HTML and Markdown
output paths.

Currently houses a single plugin: ``make_sha_plugin`` (issue #156)
which turns plain ``7c2e6f6``-shaped tokens into commit links when a
caller-supplied resolver returns a URL. Local-only commits — the
common case for in-flight work — stay as plain text so the rendered
transcript doesn't sprout broken links.

## Why a separate module

Both ``html/utils.py`` (the HTML mistune pipelines) and
``markdown/renderer.py`` (the Markdown output's tag-protecting
mistune pipeline) need to register the same plugin. Keeping the
factory here avoids the cross-import that would otherwise be needed.

## Why an inline-parser plugin (not a renderer monkey-patch)

The in-project ``_create_pygments_plugin`` precedent in
``html/utils.py`` monkey-patches ``md.renderer.block_code`` — that's
the right shape for *block*-level transformations. SHA detection is
*inline* (it has to fire mid-paragraph, inside ``*…*`` and ``**…**``,
but not inside ``` `…` ``` or fenced code), and mistune's inline
parser already provides exactly that surface via
``md.inline.register``. See
https://mistune.lepture.com/en/latest/advanced.html#create-plugins.

## Word-boundary heuristic

The default regex ``r"\\b[0-9a-f]{7,40}\\b"`` matches 7-to-40-char
lowercase hex runs at word boundaries. False-positive shapes worth
noting:

- ``0xdeadbeef`` style hex literals — the leading ``0x`` is consumed
  by ``\\b`` so the ``deadbeef`` portion does match. The resolver
  rejects unreachable SHAs, so these render as plain text in
  practice.
- 7+ char bash variable names that happen to be all hex would match
  syntactically but again, the resolver gate prevents bogus links.

The conservative pattern is fine for now; tighten if real-world
false-positive volume becomes an issue.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional


# Word-bounded run of 7-40 lowercase hex chars. Mirrors the standard
# git short-SHA shape (``git config --global core.abbrev`` defaults to
# 7); 40 is the full SHA-1 length. The resolver gate filters
# false-positives that this loose pattern lets through.
SHA_PATTERN = r"\b[0-9a-f]{7,40}\b"


def make_sha_plugin(resolve: Callable[[str], Optional[str]]) -> Any:
    """Build a mistune plugin that links resolvable git commit SHAs.

    The plugin emits a stock ``"link"`` token, so it works with both
    ``mistune.HTMLRenderer`` and the project's ``MarkdownRenderer``
    without per-renderer registration. ``resolve`` is the only
    customisation point — it returns the URL to link to, or ``None``
    to leave the SHA unchanged. Wrap it in ``functools.lru_cache``
    upstream; ``parse_sha_link`` calls it once per match.

    Args:
        resolve: callable mapping a candidate SHA to a target URL or
            ``None`` for "leave as plain text".

    Returns:
        A function suitable for the ``plugins=[...]`` list passed to
        ``mistune.create_markdown``.
    """

    def parse_sha_link(inline: Any, m: re.Match[str], state: Any) -> int:
        sha = m.group(0)
        pos = m.end()
        # Don't nest links: if we're already inside a [text](url)
        # token, drop straight through to plain-text emission. Mirrors
        # the guard in mistune's bundled ``url`` plugin.
        if getattr(state, "in_link", False):
            inline.process_text(sha, state)
            return pos
        url = resolve(sha)
        if url is None:
            # Resolver said "no" (no remote, not reachable, etc.) —
            # render as plain text exactly as it appeared.
            inline.process_text(sha, state)
            return pos
        state.append_token(
            {
                "type": "link",
                "children": [{"type": "text", "raw": sha}],
                "attrs": {"url": url},
            }
        )
        return pos

    def plugin(md: Any) -> None:
        # The outer ``Any`` return type on ``make_sha_plugin`` is a
        # deliberate hand-off to mistune's ``PluginRef`` interface,
        # which expects a positional-or-keyword ``md`` parameter.
        # Typing this closure more tightly produces a parameter-kind
        # mismatch with strict checkers (pyright/ty) at the
        # ``create_markdown(plugins=[…])`` call site.
        #
        # ``register`` appends to ``DEFAULT_RULES``, so built-in
        # inline rules (``link``, ``auto_link``, ``codespan``, …) win
        # on overlap. That's what we want: an explicit
        # ``[abc1234](url)`` stays a single link, and a SHA inside
        # ``` `…` ``` stays code.
        md.inline.register("sha_link", SHA_PATTERN, parse_sha_link)

    return plugin


def linkify_shas_in_text(text: str, resolve: Callable[[str], Optional[str]]) -> str:
    """Substitute resolvable SHAs in ``text`` with Markdown links.

    Used by the Markdown output path where text bodies are emitted
    directly (no mistune render) — e.g.
    ``MarkdownRenderer.format_AssistantTextMessage``. Mirrors the
    HTML side's plugin behaviour: only SHAs the resolver can map to
    a URL get rewritten; everything else (including SHAs inside
    inline code spans / fenced blocks) is left alone.

    The conservative scope here is that the substitution operates on
    the *raw* text, so it doesn't know about Markdown context. The
    rule of thumb: text that comes from ``TextContent`` bodies (user
    or assistant prose) is safe to scan; text that has already been
    Markdown-formatted (URLs, code spans) should be passed through
    mistune instead.
    """
    if not text:
        return text

    def _sub(m: re.Match[str]) -> str:
        sha = m.group(0)
        url = resolve(sha)
        if url is None:
            return sha
        return f"[{sha}]({url})"

    return re.sub(SHA_PATTERN, _sub, text)
