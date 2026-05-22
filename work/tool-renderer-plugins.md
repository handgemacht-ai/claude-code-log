# Tool-renderer plugin system

## Status: Design proposal (no implementation yet)

## Problem statement

Today every tool renderer is baked into `claude-code-log`: a new
tool means a PR against `claude_code_log/factories/tool_factory.py`,
`claude_code_log/html/tool_formatters.py`, and the
`format_<ClassName>` methods on the two renderer classes. This is
fine for the in-tree set (Bash, Read, WebSearch, ...), but it
prevents third parties — including the ClMail MCP plugin we use
ourselves — from shipping a *content-aware* renderer alongside
their tool. The visible symptom: `--detail low` Markdown today
shows synthetic hook lines like `[clmail] You've got a new mail
(#3076)` rather than the actual mail subject / body excerpt, because
no in-tree renderer knows what `mcp__plugin_clmail_clmail__communicate`
returns.

This document proposes a plugin mechanism that lets external
packages contribute tool renderers via setuptools entry points,
with a priority offset so an out-of-tree plugin can either
**supplement** the in-tree set (positive priority, used only if no
builtin claims the tool) or **supersede** it (negative priority,
wins until something more negative arrives). The driving use case
is the ClMail tools, but the same mechanism unlocks any future
MCP tool plus a path to pluggable output formatters (see
[Future](#future-extensions)).

## Current architecture (what we hook into)

Three dispatch points matter:

1. **`TOOL_INPUT_MODELS`** (dict) at
   `claude_code_log/factories/tool_factory.py:93` — maps tool name
   string → Pydantic input model class. `create_tool_input()`
   (line 143) looks the name up; on miss falls back to
   `ToolUseContent`.
2. **`TOOL_OUTPUT_PARSERS`** (dict) at
   `claude_code_log/factories/tool_factory.py:1234` — maps tool
   name → parser callable producing the output dataclass. Used by
   `create_tool_output()` (line 1272).
3. **`_dispatch_format`** at `claude_code_log/renderer.py:4143` —
   takes a content object, walks `type(obj).__mro__`, and calls
   `format_<ClassName>` on the renderer instance. The MRO walk
   gives free polymorphic fallback (`format_BashInput` →
   `format_ToolUseContent`).

Detail-level filtering lives at `renderer.py:3151–3224`. The
keep-list at `--detail low` is the hardcoded set
`_LOW_KEEP_TOOLS = {"WebSearch", "WebFetch", "Task", "Agent"}`.

Icons are scattered as string literals across title methods in
`html/renderer.py:843–930` (no central registry).

These are the four surfaces a plugin needs to influence. The
plugin system's whole job is to populate the first two dicts, the
third's MRO-discoverable methods, the fourth's keep-list, and a
new icon registry — from out-of-tree packages.

## Discovery + selection: `importlib.metadata.entry_points`

**Recommendation: stdlib entry points, group name
`claude_code_log.tool_renderers`.**

Compared to `pluggy`:

| | entry_points (stdlib) | pluggy |
|---|---|---|
| Dependency | zero | one (`pluggy`) |
| Declarative pyproject hook | yes | no (needs `pm.register()` calls) |
| Composition (firstresult, before/after) | no | yes |
| Mental model | "load a class by name" | "hook spec / hook impl" |
| Fits our need | yes (one winner per tool) | overkill |

We need *one* renderer per `(tool_name, output_format)` at any
time, chosen by priority — not multi-hook composition. Pluggy's
expressiveness pays for itself in pytest, where each hook can fire
multiple impls; here it would just be ceremony. Entry points stay
in the boring lane: stdlib, no new dep, mirrors how Click commands
and pytest plugins themselves are discovered.

A plugin package declares:

```toml
[project.entry-points."claude_code_log.tool_renderers"]
clmail_communicate = "claude_code_log_clmail:ClmailCommunicateRenderer"
clmail_control     = "claude_code_log_clmail:ClmailControlRenderer"
clmail_actors      = "claude_code_log_clmail:ClmailActorsRenderer"
clmail_terminal    = "claude_code_log_clmail:ClmailTerminalRenderer"
```

At startup, `claude_code_log` enumerates this group once, loads
each entry, validates against the `ToolRenderer` protocol, groups
by `tool_name`, resolves by priority, and freezes the winners
into the runtime dispatch tables. No reload at runtime; the cost
of a CLI restart is acceptable for a tool-renderer change.

## Renderer interface (Protocol sketch)

A plugin is a class implementing `ToolRenderer`. Class attributes
declare metadata; instance methods do the rendering. Methods
return `None` to defer (e.g. let Markdown→HTML conversion handle
the HTML side).

```python
from typing import ClassVar, Protocol, runtime_checkable
from claude_code_log.models import (
    TemplateMessage, ToolUseContent, ToolResultContent,
)

DetailLevel = Literal["full", "high", "medium", "low"]  # already exists

@runtime_checkable
class ToolRenderer(Protocol):
    # --- registration ---
    tool_name: ClassVar[str]              # e.g. "mcp__plugin_clmail_clmail__communicate"
    priority: ClassVar[int]               # 0 = builtin; <0 supersedes; >0 fallback
    min_detail: ClassVar[DetailLevel]     # smallest level at which this tool is rendered
    icon: ClassVar[str | None]            # optional Unicode glyph for the heading

    # --- parsing (factory side) ---
    InputModel: ClassVar[type[BaseModel]]              # Pydantic
    OutputModel: ClassVar[type[Any] | None]            # dataclass; None for unstructured

    @staticmethod
    def parse_output(raw: dict, message: TemplateMessage) -> Any | None: ...
        # default: identity (raw dict) or instantiate OutputModel from `toolUseResult`

    # --- rendering (renderer side) ---
    def render_input_markdown(self, content: ToolUseContent,
                              message: TemplateMessage) -> str: ...

    def render_output_markdown(self, content: ToolResultContent,
                               message: TemplateMessage) -> str: ...

    def render_input_html(self, content: ToolUseContent,
                          message: TemplateMessage) -> str | None: ...
        # None => fall back to mistune(render_input_markdown(...))

    def render_output_html(self, content: ToolResultContent,
                           message: TemplateMessage) -> str | None: ...

    def title(self, content: ToolUseContent,
              message: TemplateMessage) -> str | None: ...
        # None => default "{icon} {ToolName} <summary>"
```

The two-way (Markdown required, HTML optional) split is what lets
the user's stated constraint hold: **Markdown is the minimum
required output; HTML can be derived from Markdown.** When
`render_input_html` returns `None`, the system runs the plugin's
Markdown output through the same `mistune` pipeline already used
for assistant content.

Notably absent: no `render_input_json`. JSON output (see
`dev-docs/implementing-a-tool-renderer.md` §JSON) already works
generically from the dataclass / Pydantic models via
`dataclasses.asdict`; a plugin that ships the model classes gets
JSON support for free.

## Priority + detail-level resolution

Pseudocode for the discovery loop:

```python
def load_plugins() -> dict[str, ToolRenderer]:
    candidates: dict[str, list[ToolRenderer]] = defaultdict(list)
    # 1. Discover entry-point plugins.
    for ep in entry_points(group="claude_code_log.tool_renderers"):
        try:
            cls = ep.load()
        except Exception as e:
            warn(f"failed to load tool renderer plugin {ep.name!r}: {e}")
            continue
        if not isinstance(cls, type) or not isinstance(cls(), ToolRenderer):
            warn(f"plugin {ep.name!r} does not implement ToolRenderer")
            continue
        candidates[cls.tool_name].append(cls())
    # 2. Also feed in builtins as priority=0 entries.
    for tool_name, builtin in BUILTIN_RENDERERS.items():
        candidates[tool_name].append(builtin)
    # 3. Resolve: lowest priority wins; tie-break alphabetically by class name with a warning.
    winners: dict[str, ToolRenderer] = {}
    for tool_name, group in candidates.items():
        group.sort(key=lambda p: (p.priority, type(p).__name__))
        if len(group) > 1 and group[0].priority == group[1].priority:
            warn(f"tie-break for {tool_name!r} at priority {group[0].priority}: "
                 f"using {type(group[0]).__name__}")
        winners[tool_name] = group[0]
    return winners
```

The winners table is consulted at three places:

- `TOOL_INPUT_MODELS[tool_name]` ← `winner.InputModel`
- `TOOL_OUTPUT_PARSERS[tool_name]` ← `winner.parse_output`
- `_dispatch_format` consults `winners[tool_name]` when the
  content's class doesn't match a `format_<ClassName>` method on
  the renderer (today's MRO fallback path).

Detail filtering becomes data-driven:

```python
def is_tool_active_at(detail: DetailLevel, tool_name: str) -> bool:
    plugin = winners.get(tool_name)
    if plugin is None:
        return False           # unknown tool, generic fallback
    return _detail_ge(detail, plugin.min_detail)

# _detail_ge: "low" satisfies "low" / "medium" / "high" / "full" descending
```

This replaces the hardcoded `_LOW_KEEP_TOOLS` set. The in-tree
WebSearch / WebFetch / Task / Agent renderers declare
`min_detail = "low"`; everyone else defaults to `"high"` or
`"full"`. The ClMail communicate renderer declares `"low"`.

### Decisions inside the algorithm

- **`min_detail` only, no `max_detail`.** A tool *worth showing
  at low detail* is also worth showing at full detail — the user
  asked for more information, not less. A max would invert that.
  If a corner case ever needs hiding-when-verbose, the renderer
  can branch on `message.detail` inside its render method.
- **Tie-break is stable alphabetical by class name with a
  warning.** Predictable enough to debug, loud enough that an
  unintended tie surfaces. Plugins that genuinely want to stack
  should pick distinct priorities.
- **Priority 0 reserved for builtins.** Plugins should use any
  non-zero integer; the convention `-5` / `+5` (or further-out
  values) is documented but not enforced. Builtins themselves do
  not declare a priority — the loader injects them at 0.

## Worked example: ClMail tools plugin

A separate package, `claude-code-log-clmail-renderer`, ships
alongside the existing `clmail` Python package (or as a `clmail`
sub-extra). Layout:

```
claude_code_log_clmail/
  __init__.py
  _base.py                     # shared ClMail mail-format helpers
  communicate.py               # ClmailCommunicateRenderer
  control.py                   # ClmailControlRenderer
  actors.py                    # ClmailActorsRenderer
  terminal.py                  # ClmailTerminalRenderer
  templates/
    communicate.md.j2          # optional Jinja partials
```

Representative renderer (sketch only):

```python
class ClmailCommunicateRenderer:
    tool_name  = "mcp__plugin_clmail_clmail__communicate"
    priority   = -5                # supersede the generic ToolUseContent fallback
    min_detail = "low"
    icon       = "✉"

    class InputModel(BaseModel):
        action: Literal["send", "list", "read", "thread", "search",
                        "delete", "clear"]
        actor: str = ""
        params: dict | str = {}

    @dataclass
    class OutputModel:
        action: str
        # action-specific shape — discriminated union pattern, one
        # parser per action.

    @staticmethod
    def parse_output(raw, message):
        action = raw.get("action") or _infer_action_from(raw)
        return _PARSERS_BY_ACTION[action](raw)

    def render_input_markdown(self, content, message):
        match content.parsed.action:
            case "send":
                return f"**Sending to {content.parsed.params['to']}**\n\n"\
                       f"> {content.parsed.params['subject']}"
            case "read":
                return f"Reading message #{content.parsed.params['id']}"
            ...

    def render_output_markdown(self, content, message):
        # action == "read" -> render mail body excerpt + frontmatter
        # action == "list" -> count + 1-line-per-message preview
        # action == "send" -> "Sent to {to} (id {message_ids[0]})"
        ...

    # render_*_html return None -> derived from Markdown via mistune.
```

At `--detail low`, instead of:

```
[clmail] You've got a new mail (#3076)
```

the Markdown output would carry, inside the tool block:

```
✉ clmail communicate · read

Reading message #3076

> Subject: PR #164 status check — user wants you to finish it
> From: main · 2026-05-21
> Hi carol — the user said "monitor carol while she finishes #164" …
```

The synthetic hook line stays in the user-prompt stream (alice's
parallel work strips it at `--detail low`); the *content* now
lives in the rendered tool block instead.

## Test strategy

Three layers:

1. **Plugin loader unit tests** (mock entry points via
   `importlib.metadata.entry_points`'s
   `select(group=...)` and a fake EntryPoint object): cover
   priority ordering, tie-break warning, malformed plugin
   rejection, builtin injection.
2. **Renderer integration tests**: ship a `dummy_plugin` fixture
   in `test/test_data/` registering a fake tool. Drive a JSONL
   transcript through `claude-code-log` with the plugin
   discoverable, assert Markdown / HTML output picks up the
   plugin's rendering. Cover all four `(min_detail, current
   detail)` quadrants.
3. **ClMail plugin tests** (in the ClMail-renderer package, not
   here): per-action snapshot tests covering the seven
   `communicate` actions, the four `control` actions, etc. Lives
   with that package's own test suite.

Snapshot tests for the in-tree builtin set need no change beyond
declaring their `min_detail` values explicitly — the existing
snapshot pins their current output.

## Open questions (decisions deferred to implementation)

- **Plugin caching.** Entry-point discovery costs ~10ms on first
  call. If that shows in startup profiling, cache the resolved
  winners table to disk keyed by installed plugin versions. Not
  needed in v1.
- **Plugin enable/disable flag.** Should `--no-plugin <name>` or
  an env var let the user mask a plugin without uninstalling? A
  case can be made for testing; defer until requested.
- **Plugin version pinning.** No machine-readable "requires
  claude-code-log >= X.Y" yet. Use the existing pyproject
  `requires` field; we'll cross that bridge when a breaking
  Protocol change happens.
- **MCP namespace handling.** Should the system offer a sugar
  like `tool_name = "clmail__communicate"` that auto-resolves
  any `mcp__*__clmail__communicate`? Decline for v1 — plugins
  declare the exact verbatim tool name. Revisit once we have
  two MCP plugin names that collide across servers.
- **Icon source of truth.** v1 keeps icons declared per-renderer.
  An optional follow-up could migrate the in-tree scattered
  icons into a single `_ICONS: dict[str, str]` populated by the
  loader from each winner's `icon` attribute, retiring the
  hardcoded literals at `html/renderer.py:843–930`.
- **Templates.** Plugins MAY ship Jinja partials and load them
  via `importlib.resources`; we won't standardise a directory
  convention until a second plugin needs it.

## Future extensions

The same entry-point machinery extends cleanly to two adjacent
needs without changing the v1 surface:

1. **Pluggable formatters** (the user's named future direction).
   A new group `claude_code_log.formatters` discovers full
   format renderers — RTF, JATS, etc. The discovery,
   priority, and detail-level vocabulary all carry over. A
   formatter plugin would register both a name (`"rtf"`) and a
   renderer object that knows how to walk the `TemplateMessage`
   tree; tool renderers contribute `render_input_<format>` /
   `render_output_<format>` methods for any format they wish to
   support, falling back to "derive from Markdown" for the rest.
2. **Pluggable message-type renderers** (less interesting today,
   but the same shape). The current factories (`meta_factory`,
   `user_factory`, etc.) are themselves dispatch tables. The
   plugin machinery built for tools is reusable for them; the
   only delta is the dispatch key.

In neither case does v1 need to ship anything for the future —
the entry-point group `claude_code_log.tool_renderers` is scoped
narrowly enough that adding a `claude_code_log.formatters` group
later is purely additive.
