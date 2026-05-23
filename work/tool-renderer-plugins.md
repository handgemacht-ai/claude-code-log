# Plugin system: tool renderers and message transformers

## Status: Design proposal (no implementation yet)

## Problem statement

Two parallel needs both want the same plugin machinery.

**Tool renderers.** Today every tool renderer is baked into
`claude-code-log`: a new tool means a PR against
`claude_code_log/factories/tool_factory.py`,
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

**Message transformers.** In parallel, PR #167 (alice's
`dev/filter-hook-turns` branch) introduces
`detect_hook_notification()` in
`claude_code_log/factories/user_factory.py:79–99`: a regex over
`(monitor|clmail)`-prefixed user turns that demotes them from
`UserTextMessage` to a typed `UserHookNotificationMessage` which
the renderer filters at HIGH/MEDIUM/LOW/MINIMAL. The regex is
hard-coded for two specific external hook sources — exactly the
kind of plugin-shaped concern that should live with the plugin that
*causes* those notifications (the ClMail plugin), not in core.

Both problems collapse to: **external code wants to influence
which Python class wraps a parsed entry, and how that class
renders.** This document proposes a single plugin mechanism that
lets external packages contribute either kind of capability via
setuptools entry points, with a priority offset so an out-of-tree
plugin can either **supplement** the in-tree set (positive priority,
used only if no builtin claims the slot) or **supersede** it
(negative priority, wins until something more negative arrives).
The driving use cases are the ClMail tools and the clmail/monitor
hook-demotion, but the same mechanism unlocks any future MCP tool,
any future hook-injection format, plus a path to pluggable output
formatters (see [Future](#future-extensions)).

## Current architecture (what we hook into)

Six dispatch points matter — three for tool renderers, three more
that transformers touch.

**Tool-renderer surfaces:**

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
   `format_ToolUseContent`). Used by both tool renderers (for
   `ToolUseContent` subclasses) and transformers (for the
   `MessageContent` subclasses they introduce).

Detail-level filtering lives at `renderer.py:3151–3224`. The
keep-list at `--detail low` is the hardcoded set
`_LOW_KEEP_TOOLS = {"WebSearch", "WebFetch", "Task", "Agent"}`.

Icons are scattered as string literals across title methods in
`html/renderer.py:843–930` (no central registry).

**Transformer surfaces:**

4. **Factory dispatch chain** at
   `claude_code_log/factories/user_factory.py:539–568` (and the
   analogous functions for assistant / system / meta entries).
   `create_user_message` tries detectors in a fixed sequence:
   `is_command_message` → `is_local_command_output` →
   `is_bash_input / is_bash_output` → `has_teammate_message` →
   `has_task_notification` → `detect_hook_notification` (#167) →
   `is_slash_command` (isMeta) → generic text fallback. Each
   detector either claims the entry (producing a typed
   `MessageContent` subclass) or passes through. Transformers
   plug into this chain at declared priority offsets.
5. **`_HIGH_EXCLUDE_CLASSES`** (set) in `renderer.py` — the
   filter-bucket registry that drops hook-noise content at
   HIGH/MEDIUM/LOW/MINIMAL detail. Today this is a hardcoded set
   of `MessageContent` subclass references; the plugin system
   replaces it with a `detail_visibility: ClassVar[DetailLevel]`
   attribute on each `MessageContent` subclass (built-ins migrate
   in a follow-up PR after #166 lands).
6. **`extract_text_content(content_list)`** at user_factory — the
   joined-with-newlines text string that detectors regex against.
   The plugin contract guarantees that `UserTextMessage.text`
   (and equivalents on other message types) is byte-equivalent
   to this extraction, so transformer regexes behave consistently
   whether called inside the factory or against a parsed
   `MessageContent`.

These are the surfaces a plugin needs to influence. The plugin
system's whole job is to populate the tool-renderer surfaces
(1–3 plus keep-list and icon registry) and the transformer
surfaces (4–6) — from out-of-tree packages, through one shared
discovery mechanism.

## Discovery + selection: `importlib.metadata.entry_points`

**Recommendation: stdlib entry points, single group
`claude_code_log.plugins`, loader type-dispatches each entry on
Protocol conformance.**

Compared to `pluggy`:

| | entry_points (stdlib) | pluggy |
|---|---|---|
| Dependency | zero | one (`pluggy`) |
| Declarative pyproject hook | yes | no (needs `pm.register()` calls) |
| Composition (firstresult, before/after) | no | yes |
| Mental model | "load a class by name" | "hook spec / hook impl" |
| Fits our need | yes (one winner per slot) | overkill |

We need *one* winner per `(tool_name, output_format)` and one
winner per `(applies_to-type, priority)` slot, chosen by priority —
not multi-hook composition. Pluggy's expressiveness pays for
itself in pytest, where each hook can fire multiple impls; here it
would just be ceremony. Entry points stay in the boring lane:
stdlib, no new dep, mirrors how Click commands and pytest plugins
themselves are discovered.

**One group, capability inferred from class.** Both `ToolRenderer`
and `MessageTransformer` plugins register under the same
entry-point group; the loader inspects each yielded class for
Protocol conformance and routes accordingly. This matches the
pytest11 / mkdocs / mypy stubs pattern, avoids forcing pure-tool
plugins to ship a `Plugin` aggregator class, and gives a single
discovery namespace that's easy to audit (one `entry_points`
call, one place to look). A multi-capability plugin just
declares N entries.

A plugin package declares:

```toml
[project.entry-points."claude_code_log.plugins"]
# Tool renderers
clmail_communicate     = "claude_code_log_clmail.renderers:ClmailCommunicateRenderer"
clmail_control         = "claude_code_log_clmail.renderers:ClmailControlRenderer"
clmail_actors          = "claude_code_log_clmail.renderers:ClmailActorsRenderer"
clmail_terminal        = "claude_code_log_clmail.renderers:ClmailTerminalRenderer"
# Message transformers
clmail_hook_demotion   = "claude_code_log_clmail.transformers:ClmailHookDemotion"
monitor_hook_demotion  = "claude_code_log_clmail.transformers:MonitorHookDemotion"
```

At startup, `claude_code_log` enumerates this group once, loads
each entry, dispatches by Protocol (`isinstance(cls(),
ToolRenderer)` vs `isinstance(cls(), MessageTransformer)`),
resolves each capability's winners by priority, and freezes the
results into the runtime dispatch tables. No reload at runtime;
the cost of a CLI restart is acceptable for any plugin change.

## Plugin Protocols (one per capability)

A plugin is a class implementing exactly one of two Protocols:
`ToolRenderer` (renders a specific tool's input/output) or
`MessageTransformer` (rewrites a parsed `MessageContent` into a
different variant during factory dispatch). Both Protocols share
the same priority + discovery semantics so plugins can mix and
match.

### `ToolRenderer`

Class attributes
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

### `MessageTransformer`

A transformer rewrites a parsed `MessageContent` into a different
`MessageContent` variant during factory dispatch. The plugin owns
the target class — it defines the new `MessageContent` subclass,
declares its detail-level visibility, and registers its
format/title methods via the same MRO-discoverable dispatch as
built-ins.

```python
from typing import ClassVar, Optional, Protocol, runtime_checkable
from claude_code_log.models import (
    DetailLevel, MessageContent, MessageMeta,
)

@runtime_checkable
class MessageTransformer(Protocol):
    # --- registration ---
    name: ClassVar[str]                                 # e.g. "clmail.hook-demotion"
    priority: ClassVar[int]                             # built-in baseline; see priority table below
    applies_to: ClassVar[tuple[type[MessageContent], ...]]
        # MRO-filtered: only invoked when the factory's *current* candidate
        # MessageContent matches (subclass check). Most transformers target
        # (UserTextMessage,) — they only fire for entries that would
        # otherwise fall through to the generic text variant.

    # --- the new MessageContent class this transformer produces ---
    OutputClass: ClassVar[type[MessageContent]]
        # Plugin-owned. Declares detail_visibility on itself; carries
        # format_<ClassName> / title_<ClassName> methods registered
        # alongside the transformer (see below).

    # --- transformation ---
    def transform(
        self,
        text_content: str,
        content_list: list,
        meta: MessageMeta,
    ) -> Optional[MessageContent]:
        """Return an OutputClass instance, or None to pass through.

        Called inside the factory dispatch chain at this transformer's
        declared priority. text_content is byte-equivalent to what the
        factory's built-in detectors consume.
        """

    # --- renderer methods (registered alongside the transformer) ---
    # Plugin defines format_<ClassName> and title_<ClassName> functions
    # for the OutputClass; the loader binds them onto the renderer
    # classes the same way built-in formatters work. Signature mirrors
    # the existing convention in renderer.py / html/renderer.py /
    # markdown/renderer.py.
```

The plugin-owned `OutputClass` declares its visibility directly:

```python
class UserHookNotificationMessage(MessageContent):
    source: str   # "monitor" or "clmail"
    text: str

    detail_visibility: ClassVar[DetailLevel] = DetailLevel.FULL
        # Only visible at --detail full; dropped at HIGH/MEDIUM/LOW/MINIMAL.
```

This replaces the hardcoded `_HIGH_EXCLUDE_CLASSES` registry: the
renderer's filter pass reads `cls.detail_visibility` (with a
default of `DetailLevel.MINIMAL` = always visible) instead of
consulting a central set. Built-in `MessageContent` subclasses
migrate to the class-attribute form in a follow-up PR — mechanical
diff, doesn't block #166.

**In-factory-dispatch placement.** Transformers run *inside* the
factory's existing detector sequence, not as a post-factory pass.
Concretely, `create_user_message` (and analogues) walks a single
unified priority-ordered list: built-in detectors interleaved with
registered transformers, each checked in turn. This preserves the
existing ordering invariants (`is_slash_command` always wins
before any text-targeting transformer can fire) and avoids
re-walking the tree.

**Multi-line guards and other matcher-specific concerns** live in
the plugin, not the core contract. A transformer that wants to
reject multi-line bodies (clmail's case) does so inside its own
`transform()`; a transformer that wants to accept them is free to.

## Priority + detail-level resolution

Pseudocode for the discovery loop:

```python
def load_plugins() -> tuple[dict[str, ToolRenderer], list[MessageTransformer]]:
    renderer_candidates: dict[str, list[ToolRenderer]] = defaultdict(list)
    transformers: list[MessageTransformer] = []
    # 1. Discover entry-point plugins; dispatch on Protocol.
    for ep in entry_points(group="claude_code_log.plugins"):
        try:
            cls = ep.load()
            instance = cls()
        except Exception as e:
            warn(f"failed to load plugin {ep.name!r}: {e}")
            continue
        if isinstance(instance, ToolRenderer):
            renderer_candidates[cls.tool_name].append(instance)
        elif isinstance(instance, MessageTransformer):
            transformers.append(instance)
            _register_format_methods(cls.OutputClass)  # binds plugin's format_X/title_X
        else:
            warn(f"plugin {ep.name!r} does not implement any plugin Protocol")
    # 2. Feed in builtins as priority=0 entries.
    for tool_name, builtin in BUILTIN_RENDERERS.items():
        renderer_candidates[tool_name].append(builtin)
    # 3. Resolve renderers: lowest priority wins; tie-break alphabetically by class name with a warning.
    winners: dict[str, ToolRenderer] = {}
    for tool_name, group in renderer_candidates.items():
        group.sort(key=lambda p: (p.priority, type(p).__name__))
        if len(group) > 1 and group[0].priority == group[1].priority:
            warn(f"tie-break for {tool_name!r} at priority {group[0].priority}: "
                 f"using {type(group[0]).__name__}")
        winners[tool_name] = group[0]
    # 4. Sort transformers globally by priority (no per-slot grouping; factory
    #    consults them in order alongside built-in detectors).
    transformers.sort(key=lambda t: (t.priority, type(t).__name__))
    return winners, transformers
```

### Built-in detector priority table

Transformers position themselves relative to the in-factory
detector sequence. Built-in detectors get explicit named
priorities exposed as module constants, with gaps of 100 to leave
room for plugin insertion without renumbering:

```python
# claude_code_log.factories.priorities
COMMAND_MESSAGE           = 100
LOCAL_COMMAND_OUTPUT      = 200
BASH_INPUT_OUTPUT         = 300
TEAMMATE_MESSAGE          = 400
TASK_NOTIFICATION         = 500
HOOK_NOTIFICATION         = 600   # alice's #167 default seat
SLASH_COMMAND_ISMETA      = 700
TEXT_FALLBACK             = 1000  # always last; generic UserTextMessage
```

A clmail-plugin transformer registered at `priority=600` *replaces*
the hardcoded hook detector. At `priority=550` it runs *before* it
(useful only to override built-in behaviour). At `priority=650` it
runs *after* it (useful as a fallback if the built-in eventually
narrows its scope). Lower number = higher priority = runs first;
first non-None wins.

### Subtle ordering note

`applies_to = (UserTextMessage,)` is the natural scope for any
text-prefix transformer: it only fires on entries that have not
already been claimed by an earlier detector. A transformer cannot
accidentally intercept a slash-command, bash-input, or
teammate-message entry, because those never become `UserTextMessage`
in the first place. This is a real safety property, not just a
micro-optimization — the existing factory ordering enforces
plugin precedence by class assignment.

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

## Worked example: ClMail plugin (renderers + transformers)

A separate package, `claude-code-log-clmail`, ships alongside the
existing `clmail` Python package (or as a `clmail` sub-extra). One
package provides both capabilities — content-aware renderers for
the four ClMail MCP tools *and* the message transformers that
demote `[clmail]` / `[monitor]` user turns to hook-notification
noise. Layout:

```
claude_code_log_clmail/
  __init__.py
  _base.py                     # shared mail-format helpers
  renderers/
    __init__.py
    communicate.py             # ClmailCommunicateRenderer
    control.py                 # ClmailControlRenderer
    actors.py                  # ClmailActorsRenderer
    terminal.py                # ClmailTerminalRenderer
  transformers/
    __init__.py
    hook_demotion.py           # ClmailHookDemotion, MonitorHookDemotion
                               #   + UserHookNotificationMessage (the OutputClass)
  templates/
    communicate.md.j2          # optional Jinja partials
```

### Transformer side (replaces alice's hardcoded regex)

`detect_hook_notification()` from
`claude_code_log/factories/user_factory.py:79–99` reduces to a
~12-line plugin transformer. The plugin owns the
`UserHookNotificationMessage` class outright; core knows nothing
about `[monitor]` or `[clmail]` prefixes.

```python
# claude_code_log_clmail/transformers/hook_demotion.py
import re
from typing import ClassVar
from claude_code_log.models import (
    DetailLevel, MessageContent, MessageMeta, UserTextMessage,
)
from claude_code_log.factories.priorities import HOOK_NOTIFICATION


class UserHookNotificationMessage(MessageContent):
    source: str   # "monitor" | "clmail" | future plugin-defined sources
    text: str
    detail_visibility: ClassVar[DetailLevel] = DetailLevel.FULL


def _make_hook_transformer(source: str, priority_offset: int = 0):
    pattern = re.compile(rf"^\s*\[{source}\]\s*(.*?)\s*\Z", re.DOTALL)

    class _HookDemotion:
        name       = f"clmail.{source}-hook-demotion"
        priority   = HOOK_NOTIFICATION + priority_offset
        applies_to = (UserTextMessage,)
        OutputClass = UserHookNotificationMessage

        def transform(self, text_content, content_list, meta):
            m = pattern.match(text_content)
            if m is None or "\n" in m.group(1):
                return None         # multi-line guard: real prompt, not hook
            return UserHookNotificationMessage(
                source=source, text=m.group(1), meta=meta,
            )

    _HookDemotion.__name__ = f"{source.title()}HookDemotion"
    return _HookDemotion


ClmailHookDemotion  = _make_hook_transformer("clmail")
MonitorHookDemotion = _make_hook_transformer("monitor")


# Renderer methods registered alongside the OutputClass.
def format_UserHookNotificationMessage(self, content, message):
    return f"_[{content.source}] {content.text}_"


def title_UserHookNotificationMessage(self, content, message):
    return None   # headless — appears inline
```

The plugin loader, on discovering the transformer, registers
`format_UserHookNotificationMessage` and
`title_UserHookNotificationMessage` onto the Markdown and HTML
renderer classes via the existing MRO-discoverable dispatch. No
core changes needed beyond the loader itself.

### Renderer side

Representative tool renderer (sketch only):

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

Four layers:

1. **Plugin loader unit tests** (mock entry points via
   `importlib.metadata.entry_points`'s
   `select(group=...)` and a fake EntryPoint object): cover
   priority ordering, tie-break warning, malformed plugin
   rejection, builtin injection, Protocol dispatch
   (`ToolRenderer` vs `MessageTransformer` routing), and
   format-method binding for transformer-defined classes.
2. **Renderer integration tests**: ship a `dummy_renderer_plugin`
   fixture in `test/test_data/` registering a fake tool. Drive a
   JSONL transcript through `claude-code-log` with the plugin
   discoverable, assert Markdown / HTML output picks up the
   plugin's rendering. Cover all four `(min_detail, current
   detail)` quadrants.
3. **Transformer integration tests**: ship a
   `dummy_transformer_plugin` fixture introducing a new
   `MessageContent` subclass with `detail_visibility = FULL`.
   Drive a JSONL transcript carrying a matching prefix; assert
   the transformer fires inside the factory chain, the new class
   is dispatched to format/title methods, and the entry is
   filtered out at HIGH/MEDIUM/LOW/MINIMAL.
4. **ClMail plugin tests** (in the ClMail plugin package, not
   here): per-action snapshot tests covering the seven
   `communicate` actions, the four `control` actions, etc., plus
   transformer tests for `[clmail]` / `[monitor]` demotion
   (porting over alice's `test_hook_user_notifications.py` cases
   from the #167 branch). Lives with that package's own test
   suite.

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
- **Built-in migration to `detail_visibility`.** Existing
  built-in `MessageContent` subclasses currently have visibility
  encoded in `_HIGH_EXCLUDE_CLASSES`. Migration to the
  class-attribute form is mechanical and lands in a follow-up
  PR after #166 — doesn't block the plugin API.
- **Transformer surfacing / namespace collision diagnosis.** No
  `--list-plugins` CLI in v1. If two plugins claim overlapping
  prefixes (e.g. two competing `[monitor]` transformers), the
  priority field resolves who wins, but the user has no easy way
  to see *that* it happened. Consider startup log + `--list-plugins`
  in a follow-up once we have evidence of collisions in the wild.
- **Transformer chaining.** v1 is first-non-None-wins, no
  chaining. Chaining ("transformer A produces a `FooMessage`;
  transformer B targets `FooMessage` and rewrites further") is
  expressively richer but opens "plugin A's transform breaks
  plugin B's matcher" debug rabbit holes. Revisit only with a
  concrete use case.
- **Transformer scope: user-only by default vs all entry types.**
  v1 lets `applies_to` accept any `MessageContent` subtype (no
  artificial restriction); the natural worked example is
  `(UserTextMessage,)` but a transformer targeting
  `AssistantTextMessage` or a tool-result variant is permitted.
  We'll see what plugins actually do.

## Future extensions

The same entry-point machinery extends cleanly to one adjacent
need without changing the v1 surface:

1. **Pluggable formatters** (the user's named future direction).
   A new group `claude_code_log.formatters` discovers full
   format renderers — RTF, JATS, etc. The discovery,
   priority, and detail-level vocabulary all carry over. A
   formatter plugin would register both a name (`"rtf"`) and a
   renderer object that knows how to walk the `TemplateMessage`
   tree; tool renderers contribute `render_input_<format>` /
   `render_output_<format>` methods for any format they wish to
   support, falling back to "derive from Markdown" for the rest.

(An earlier draft of this section listed "pluggable message-type
renderers" as a second future extension. That's now covered
directly by `MessageTransformer` for the rewrite-to-another-variant
case. The remaining gap — plugins introducing entirely new
top-level *factory* dispatch chains rather than transforming inside
an existing one — is a much larger surface and not on the
near-term roadmap.)

In neither case does v1 need to ship anything for the future —
the entry-point group `claude_code_log.plugins` is scoped
narrowly enough that adding a `claude_code_log.formatters` group
later is purely additive.
