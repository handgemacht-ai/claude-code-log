# Plugin system: unified message-transformer mechanism

## Status: Design proposal (no implementation yet)

## Design reversal acknowledgement

This RFC went through a substantial restructure during design
review. Earlier commits proposed two parallel plugin mechanisms
(`ToolRenderer` + `MessageTransformer`), then narrowed the
transformer side to "existing core variants only" for v1 surface
reasons, then — on a pointed question from the user via main
(clmail #3132) — collapsed both mechanisms into one.

The current direction: **a single `MessageTransformer` Protocol**
that handles both the hook-demotion case AND the MCP-tool-rendering
case, by letting plugins rewrite generic content (`UserTextMessage`,
`ToolUseContent`, `ToolResultContent`, ...) into plugin-defined
specialized subclasses that carry their own format/title methods.

This is a deliberate expansion of v1 surface area (plugins now
define `MessageContent` subclasses, register format-method
contributions, and declare detail-level visibility) chosen for
architectural symmetry: built-in tools already use specialized
subclasses dispatched via MRO (`BashInputContent` and friends).
The two-mechanism split was a workaround for plugins not having
method-binding; eliminate the workaround and one mechanism
suffices for both cases.

See [the reversal context](#reversal-context-and-trade-offs) for
the design considerations the user weighed.

## Problem statement

Two motivating cases:

**Tool rendering.** Today every tool renderer is baked into
`claude-code-log`. The factory (`tool_factory.py`) maps tool name
to a specialized `ToolUseContent` subclass (`BashInputContent`,
`ReadInputContent`, etc.); the renderer dispatches to
`format_BashInput` via the MRO walk in `_dispatch_format`. This is
fine for the in-tree set but prevents third parties — including
the ClMail MCP plugin we use ourselves — from shipping a
*content-aware* renderer alongside their tool. Visible symptom:
`--detail low` Markdown today shows synthetic hook lines like
`[clmail] You've got a new mail (#3076)` rather than the actual
mail subject / body excerpt.

**Hook-injected user turns.** PR #167 (alice's
`dev/filter-hook-turns`) introduces `detect_hook_notification()`
in `claude_code_log/factories/user_factory.py:79–99`: a regex over
`(monitor|clmail)`-prefixed user turns that demotes them from
`UserTextMessage` to a typed `UserHookNotificationMessage`. The
regex is hard-coded for two specific external hook sources —
exactly the kind of plugin-shaped concern that belongs with the
plugin that *causes* those notifications.

Both cases share a single shape: **external code wants to rewrite
a parsed `MessageContent` into a plugin-defined subclass, then
have that subclass render itself.** This document proposes one
plugin mechanism — message transformers + plugin-defined
`MessageContent` subclasses — that handles both.

## Current architecture (what we hook into)

The architecture today is more plugin-friendly than the original
RFC framing suggested. The key observation: **the factory already
creates specialized subclasses, and `_dispatch_format` already
finds their format methods via MRO walk.** A plugin extension
that produces *more* specialized subclasses needs only to (a) hook
into the factory's classification step and (b) supply format
methods that the existing MRO walk can find.

Three surfaces matter:

1. **Factory dispatch chain** at
   `claude_code_log/factories/user_factory.py:539–568` (and the
   analogous functions for assistant / system / meta / tool entries).
   `create_user_message` tries detectors in a fixed sequence:
   `is_command_message` → `is_local_command_output` →
   `is_bash_input / is_bash_output` → `has_teammate_message` →
   `has_task_notification` → `detect_hook_notification` (#167) →
   `is_slash_command` (isMeta) → generic text fallback. Each
   detector either claims the entry (producing a specialized
   `MessageContent` subclass) or passes through. The tool factory
   at `tool_factory.py:93+` does the equivalent for tool entries
   via `TOOL_INPUT_MODELS[tool_name]` and `TOOL_OUTPUT_PARSERS`.
   Transformers plug into these chains at declared priority offsets.

2. **`_dispatch_format`** at `claude_code_log/renderer.py:4143` —
   takes a content object, walks `type(obj).__mro__`, and calls
   `format_<ClassName>` on the renderer instance. The MRO walk
   gives free polymorphic fallback (`format_BashInput` →
   `format_ToolUseContent`). This is the central dispatch point;
   the plugin mechanism extends it with a second resolution step
   (class-defined `format_markdown` / `format_html` / `title`
   methods on the content class itself).

3. **`extract_text_content(content_list)`** at user_factory — the
   joined-with-newlines text string that detectors regex against.
   The plugin contract guarantees that `UserTextMessage.text`
   (and equivalents on other message types) is byte-equivalent
   to this extraction, so transformer regexes behave consistently
   whether called inside the factory or against a parsed
   `MessageContent`. **Enforcement.** The plugin-system test suite
   includes a dedicated equivalence test walking the existing
   JSONL test corpus and asserting
   `UserTextMessage(content_list=cl).text == extract_text_content(cl)`
   for every user entry. A future factory PR that introduces
   normalization between extraction and assignment fails this test.

Detail-level filtering for hook-noise lives in
`_HIGH_EXCLUDE_CLASSES` (renderer.py); the keep-list at
`--detail low` is `_LOW_KEEP_TOOLS = {"WebSearch", "WebFetch",
"Task", "Agent"}`. The plugin mechanism replaces both with a
class-level `detail_visibility` attribute; see [detail-visibility
semantics](#detail_visibility-semantics-and-built-in-bridge).

Icons remain scattered as string literals across title methods
in `html/renderer.py:843–930`. Plugins can place their own icons
in the title methods they ship; centralization is a follow-up.

## Discovery + selection: `importlib.metadata.entry_points`

**Recommendation: stdlib entry points, single group
`claude_code_log.plugins`.**

Compared to `pluggy`:

| | entry_points (stdlib) | pluggy |
|---|---|---|
| Dependency | zero | one (`pluggy`) |
| Declarative pyproject hook | yes | no (needs `pm.register()` calls) |
| Composition (firstresult, before/after) | no | yes |
| Mental model | "load a class by name" | "hook spec / hook impl" |
| Fits our need | yes (first non-None wins) | overkill |

We need *one* transformer per `(applies_to-type, priority)` slot,
chosen by priority — not multi-hook composition. Pluggy's
expressiveness pays for itself in pytest; here it would just be
ceremony.

One group, one Protocol, idiomatic Python. A plugin package
declares any number of `MessageTransformer` classes:

```toml
[project.entry-points."claude_code_log.plugins"]
# Hook-demotion transformers (rewrite UserTextMessage)
clmail_hook_demotion   = "claude_code_log_clmail.transformers:ClmailHookDemotion"
monitor_hook_demotion  = "claude_code_log_clmail.transformers:MonitorHookDemotion"
# Tool-rendering transformers (rewrite ToolUseContent / ToolResultContent)
clmail_communicate_in  = "claude_code_log_clmail.transformers:ClmailCommunicateInputTransformer"
clmail_communicate_out = "claude_code_log_clmail.transformers:ClmailCommunicateOutputTransformer"
clmail_control_in      = "claude_code_log_clmail.transformers:ClmailControlInputTransformer"
clmail_control_out     = "claude_code_log_clmail.transformers:ClmailControlOutputTransformer"
# (analogous for actors, terminal)
```

At startup, `claude_code_log` enumerates this group once, loads
each entry, validates against the `MessageTransformer` Protocol,
sorts globally by priority, and freezes the result. No reload at
runtime.

## The `MessageTransformer` Protocol

```python
from typing import ClassVar, Optional, Protocol, runtime_checkable
from claude_code_log.models import MessageContent, MessageMeta

@runtime_checkable
class MessageTransformer(Protocol):
    # --- registration ---
    name: ClassVar[str]                                 # e.g. "clmail.hook-demotion"
    priority: ClassVar[int]                             # see priority table
    applies_to: ClassVar[tuple[type[MessageContent], ...]]
        # MRO-filtered: only invoked when the factory's *current* candidate
        # MessageContent matches (subclass check). Examples:
        #   (UserTextMessage,)       hook-demotion transformers
        #   (ToolUseContent,)        tool-rendering input transformers
        #   (ToolResultContent,)     tool-rendering output transformers

    # --- transformation ---
    def transform(
        self,
        content: MessageContent,
        meta: MessageMeta,
    ) -> Optional[MessageContent]:
        """Return a replacement MessageContent (typically a plugin-defined
        subclass), or None to pass through. Called inside the factory
        dispatch chain at this transformer's declared priority.
        """
```

Notable design choices:

- **Input is the parsed content**, not raw text or content_list.
  This works for both `UserTextMessage` (where text-prefix matching
  reads `content.text`) and `ToolUseContent` (where tool-name
  matching reads `content.tool_name`). Plugins access whatever
  fields they need on the typed content.
- **Output is `Optional[MessageContent]`**, not constrained to any
  particular base class. v1 accepts any subclass; convention is
  that transformers produce *more specific* subclasses of their
  `applies_to` types (e.g. a `ToolUseContent` transformer
  typically returns a `ClMailCommunicateInput(ToolUseContent)`).
- **No `OutputClass` field on the transformer.** The output
  class is whatever the `transform()` method returns; the loader
  doesn't need to know it ahead of time. The plugin author defines
  the subclass and instantiates it inside `transform()`.

## Plugin-defined `MessageContent` subclasses

Plugins define new `MessageContent` subclasses freely. The class
declares its rendering and visibility on itself:

```python
from typing import ClassVar
from pydantic import BaseModel
from claude_code_log.models import DetailLevel, ToolUseContent


class ClMailCommunicateModel(BaseModel):
    action: Literal["send", "list", "read", "thread", "search", "delete", "clear"]
    actor: str = ""
    params: dict | str = {}


class ClMailCommunicateInput(ToolUseContent):
    parsed: ClMailCommunicateModel
    detail_visibility: ClassVar[DetailLevel] = DetailLevel.LOW

    def format_markdown(self, renderer, message) -> str:
        match self.parsed.action:
            case "send":
                return (f"**Sending to {self.parsed.params['to']}**\n\n"
                        f"> {self.parsed.params['subject']}")
            case "read":
                return f"Reading message #{self.parsed.params['id']}"
            ...

    def format_html(self, renderer, message) -> str | None:
        return None    # fall back to mistune(format_markdown)

    def title(self, renderer, message) -> str | None:
        return f"✉ ClMail communicate · {self.parsed.action}"
```

`_dispatch_format` finds these methods at render time via a
two-step resolution (see below). No global registry, no
monkey-patching of renderer classes, no descriptor protocol
gymnastics — the methods live on the class, the dispatcher knows
where to look.

**This is a deliberate philosophy shift.** Today's `MessageContent`
subclasses are pure data; renderers are methods on renderer
classes. Adding `format_*` / `title` as methods on content
classes themselves means the content class now knows about
rendering. The trade-off is symmetry (one place to look for "how
does this class render") and plugin ergonomics (no separate
binding step). Built-in `MessageContent` subclasses remain
unaltered in v1; they're rendered by the existing
`format_<ClassName>` renderer methods. Migration of built-ins to
the class-method pattern is a follow-up PR and is optional — the
two patterns coexist cleanly.

## `detail_visibility` semantics and built-in bridge

A `MessageContent` subclass with a `detail_visibility: ClassVar[DetailLevel]`
attribute is rendered iff
`current_detail >= cls.detail_visibility` in the canonical
`DetailLevel` ordering. Pin the ordering once in `renderer.py`:

```
FULL  > HIGH  > MEDIUM  > LOW  > MINIMAL  > USER_ONLY
```

(Will verify against the actual enum at implementation time;
the exact spelling of the levels is whatever `DetailLevel`
currently defines. The semantics are: higher = more verbose; a
class with `detail_visibility = LOW` is rendered at `--detail
low`/`medium`/`high`/`full`, dropped at `--detail minimal`/`user-only`.)

**Default.** A `MessageContent` subclass without a
`detail_visibility` attribute defaults to `USER_ONLY` (always
visible). Plugins MUST set the attribute explicitly when they
want filtering behaviour.

**Built-in bridge.** v1 does not migrate built-in
`MessageContent` subclasses to the class-attribute form. The
existing `_HIGH_EXCLUDE_CLASSES` set in `renderer.py` continues
to govern built-in visibility. Resolution order at the filter
pass:

```python
def is_visible(content_cls: type, current_detail: DetailLevel) -> bool:
    # 1. Class attribute wins if present (plugin classes, future migrated built-ins).
    if hasattr(content_cls, "detail_visibility"):
        return current_detail >= content_cls.detail_visibility
    # 2. _HIGH_EXCLUDE_CLASSES bridge for built-ins not yet migrated.
    if content_cls in _HIGH_EXCLUDE_CLASSES:
        return current_detail == DetailLevel.FULL
    # 3. Default visible.
    return True
```

A built-in that's both in `_HIGH_EXCLUDE_CLASSES` *and* later
gets a `detail_visibility` attribute (during follow-up migration)
honours the attribute; the registry entry becomes dead code and
can be removed in the same PR. Plugin classes never appear in
`_HIGH_EXCLUDE_CLASSES`; they always use the attribute.

## `_dispatch_format` resolution order

When the renderer needs to format a content object, the lookup
walks the content's MRO and tries two strategies at each class:

```python
def _dispatch_format(self, content, message, output_format):
    method_attr = f"format_{output_format}"     # "format_markdown" / "format_html"
    for klass in type(content).__mro__:
        # Strategy 1: renderer-side format_<ClassName> method.
        # Preserves built-in dispatch unchanged; the renderer class
        # carries hand-written format_BashInput / format_ReadInput / etc.
        renderer_method = getattr(self, f"format_{klass.__name__}", None)
        if renderer_method is not None:
            return renderer_method(content, message)
        # Strategy 2: class-side format_<output> method.
        # Plugin-defined classes carry format_markdown / format_html on
        # themselves; the dispatcher invokes them with the renderer as
        # first arg so they have access to renderer state (mistune, etc.).
        class_method = klass.__dict__.get(method_attr)
        if class_method is not None:
            return class_method(content, self, message)
    raise NotImplementedError(...)
```

The `message: TemplateMessage` argument is part of the renderer's
call contract everywhere else (`format_<ClassName>` methods on the
renderer classes take `(self, content, message)`). The dispatcher
passes it through to both strategies; class-side `format_*`
methods on plugin-defined `MessageContent` subclasses have the
signature `(self, renderer, message) -> str`. The
`MessageContent` base class itself does NOT carry a back-pointer
to its `TemplateMessage`; only the renderer's caller knows
the binding, and the dispatcher is responsible for threading it.

**Four-way matrix** (for a given content class):

| renderer-method present | class-method present | Winner |
|---|---|---|
| yes | yes | renderer-method (precedence by MRO position; ties resolved by strategy order at the same level) |
| yes | no | renderer-method |
| no | yes | class-method |
| no | no | continue MRO walk; raise if exhausted |

The "renderer-method wins" rule preserves all existing built-in
dispatch unchanged — no regression risk. A plugin that subclasses
a built-in (e.g. `ClMailCommunicateInput(ToolUseContent)`) can
shadow the built-in `format_ToolUseContent` by defining
`format_markdown` on the plugin class — the MRO walk visits
`ClMailCommunicateInput` first, finds class-side `format_markdown`,
uses it, never reaches `ToolUseContent`'s renderer-side
`format_ToolUseContent`.

If `format_html` is absent (only `format_markdown` defined), the
HTML pipeline falls back to `mistune_render(format_markdown(...))`
— same convention as the original RFC's two-way split.

## Priority + ordering

Built-in detector priorities are exposed as module constants
with gaps of 100 so plugins position relative without renumbering:

```python
# claude_code_log.factories.priorities
COMMAND_MESSAGE           = 100
LOCAL_COMMAND_OUTPUT      = 200
BASH_INPUT_OUTPUT         = 300
TEAMMATE_MESSAGE          = 400
TASK_NOTIFICATION         = 500
HOOK_NOTIFICATION         = 600   # PR #167's seat
SLASH_COMMAND_ISMETA      = 700
TEXT_FALLBACK             = 1000  # generic UserTextMessage
# Tool side:
TOOL_INPUT_GENERIC        = 5000
TOOL_OUTPUT_GENERIC       = 5100
```

A clmail tool-rendering transformer at priority `4500` runs
*before* the generic tool input classification (so the generic
`ToolUseContent` is never produced for matched tools; the plugin's
`ClMailCommunicateInput` is). A hook-demotion transformer at
priority `600` *replaces* the in-core hook detector during the
migration.

Lower number = higher priority = runs first; first non-None
return wins. Tie-break is stable alphabetical by class name with
a startup warning.

### Subtle ordering note

`applies_to = (UserTextMessage,)` is the natural scope for any
text-prefix transformer: the transformer fires only on entries
that have not already been claimed by an earlier detector. A
text-prefix transformer cannot accidentally intercept a
slash-command or bash-input entry, because those never become
`UserTextMessage` in the first place. This is a real safety
property: factory ordering enforces plugin precedence by class
assignment.

For tool-rendering transformers, the analogous safety property:
`applies_to = (ToolUseContent,)` matches only entries the tool
factory has classified as generic tool input (i.e. not already
specialized to `BashInputContent`, `ReadInputContent`, etc.). The
plugin's `transform()` then narrows by `content.tool_name` to
target a specific tool.

## Loader pseudocode

```python
def load_plugins() -> list[MessageTransformer]:
    transformers: list[MessageTransformer] = []
    for ep in entry_points(group="claude_code_log.plugins"):
        try:
            cls = ep.load()
            instance = cls()
        except Exception as e:
            warn(f"failed to load plugin {ep.name!r}: {e}")
            continue
        if not isinstance(instance, MessageTransformer):
            warn(f"plugin {ep.name!r} does not implement MessageTransformer")
            continue
        transformers.append(instance)
    transformers.sort(
        key=lambda t: (t.priority, type(t).__module__, type(t).__qualname__)
    )
    # Tie-break warning
    for a, b in zip(transformers, transformers[1:]):
        if a.priority == b.priority and a.applies_to == b.applies_to:
            warn(f"priority tie for {a.applies_to!r}: "
                 f"using {type(a).__module__}.{type(a).__qualname__} before "
                 f"{type(b).__module__}.{type(b).__qualname__}")
    return transformers
```

The factory's dispatch chain consults this list at each detector
slot: for each transformer whose priority slots into the
current position and whose `applies_to` matches the current
candidate's class, call `transform()`; first non-None return wins
and replaces the candidate.

## Worked example: ClMail plugin

A single package, `claude-code-log-clmail`, ships both the
hook-demotion transformers AND the tool-rendering transformers
for the four ClMail MCP tools. One mechanism, one Protocol, one
Plugin folder.

Layout:

```
claude_code_log_clmail/
  __init__.py
  _base.py                     # shared mail-format helpers
  transformers/
    __init__.py
    hook_demotion.py           # ClmailHookDemotion, MonitorHookDemotion
                               # (rewrite UserTextMessage → UserHookNotificationMessage)
    communicate.py             # ClmailCommunicateInput + ...Output + transformers
    control.py                 # ClmailControlInput + ...Output + transformers
    actors.py
    terminal.py
  templates/
    communicate.md.j2          # optional Jinja partials
```

### Hook-demotion transformer (replaces alice's hardcoded regex)

```python
# claude_code_log_clmail/transformers/hook_demotion.py
import re
from typing import ClassVar
from pydantic import BaseModel
from claude_code_log.models import (
    DetailLevel, MessageContent, MessageMeta, UserTextMessage, UserMessage,
)
from claude_code_log.factories.priorities import HOOK_NOTIFICATION


class UserHookNotificationMessage(UserMessage):
    source: str    # "monitor", "clmail", ...
    text: str
    detail_visibility: ClassVar[DetailLevel] = DetailLevel.FULL

    def format_markdown(self, renderer, message) -> str:
        return f"_[{self.source}] {self.text}_"

    def format_html(self, renderer, message) -> str | None:
        return None    # mistune fallback

    def title(self, renderer, message) -> str | None:
        return None    # headless; appears inline


def _make_hook_transformer(source: str):
    pattern = re.compile(rf"^\s*\[{source}\]\s*(.*?)\s*\Z", re.DOTALL)

    class _HookDemotion:
        name       = f"clmail.{source}-hook-demotion"
        priority   = HOOK_NOTIFICATION
        applies_to = (UserTextMessage,)

        def transform(self, content, meta):
            m = pattern.match(content.text)
            if m is None or "\n" in m.group(1):
                return None
            return UserHookNotificationMessage(
                source=source, text=m.group(1), meta=meta,
            )

    _HookDemotion.__name__ = f"{source.title()}HookDemotion"
    return _HookDemotion


ClmailHookDemotion  = _make_hook_transformer("clmail")
MonitorHookDemotion = _make_hook_transformer("monitor")
```

When the clmail plugin is installed, PR #167's
`detect_hook_notification()` + `_HOOK_NOTIFICATION_SOURCES` tuple
+ the call site in `create_user_message` all delete from core.
`UserHookNotificationMessage` (and its format/title methods and
CSS) move out with them. Migration is one PR, mechanical.

### Tool-rendering transformer (replaces ClmailCommunicateRenderer)

```python
# claude_code_log_clmail/transformers/communicate.py
from typing import ClassVar, Literal
from pydantic import BaseModel
from claude_code_log.models import (
    DetailLevel, ToolUseContent, ToolResultContent, MessageMeta,
)
from claude_code_log.factories.priorities import TOOL_INPUT_GENERIC, TOOL_OUTPUT_GENERIC

TOOL_NAME = "mcp__plugin_clmail_clmail__communicate"


class ClmailCommunicateModel(BaseModel):
    action: Literal["send", "list", "read", "thread", "search", "delete", "clear"]
    actor: str = ""
    params: dict | str = {}


class ClmailCommunicateInput(ToolUseContent):
    parsed: ClmailCommunicateModel
    detail_visibility: ClassVar[DetailLevel] = DetailLevel.LOW

    def format_markdown(self, renderer, message) -> str:
        match self.parsed.action:
            case "send":
                return (f"**Sending to {self.parsed.params['to']}**\n\n"
                        f"> {self.parsed.params['subject']}")
            case "read":
                return f"Reading message #{self.parsed.params['id']}"
            case "list":
                return "Listing unread mail"
            ...

    def format_html(self, renderer, message) -> str | None:
        return None

    def title(self, renderer, message) -> str | None:
        return f"✉ ClMail communicate · {self.parsed.action}"


class ClmailCommunicateInputTransformer:
    name       = "clmail.communicate.input"
    priority   = TOOL_INPUT_GENERIC - 500    # supersede generic tool input
    applies_to = (ToolUseContent,)

    def transform(self, content, meta):
        if content.tool_name != TOOL_NAME:
            return None
        return ClmailCommunicateInput(
            tool_name=content.tool_name,
            tool_use_id=content.tool_use_id,
            parsed=ClmailCommunicateModel(**content.raw_input),
            meta=meta,
            **{k: getattr(content, k) for k in _PRESERVED_TOOLUSE_FIELDS},
        )


# (analogous classes for ClmailCommunicateOutput / ClmailCommunicateOutputTransformer)
```

At `--detail low`, instead of:

```
[clmail] You've got a new mail (#3076)
```

the Markdown output carries, inside the tool block:

```
✉ ClMail communicate · read

Reading message #3076

> Subject: PR #164 status check
> From: main · 2026-05-21
> ...
```

The hook-demotion transformer strips the synthetic
`[clmail] ...` line from the user prompt stream; the
tool-rendering transformer surfaces the actual content. One
plugin, both improvements, one mechanism.

### `terminal__look` auto-filtering (illustrates `detail_visibility` reuse)

```python
class ClmailTerminalLookInput(ToolUseContent):
    detail_visibility: ClassVar[DetailLevel] = DetailLevel.FULL
    # ... format methods ...
```

Setting `detail_visibility = FULL` on a noisy low-value tool's
specialized subclass auto-filters it at LOW/MEDIUM/HIGH — same
mechanism the hook-demotion case uses. No separate `_LOW_KEEP_TOOLS`
list to update.

## Test-embedded reference plugin

A minimal version of `claude-code-log-clmail` lives in
`test/_plugins/clmail/` (or similar path). Two roles:

1. **Layer-4 test fixture.** Plugin-system tests use this real
   plugin as their fixture, not mocks. The contract is validated
   end-to-end: entry-point discovery, Protocol conformance,
   transformer dispatch, `format_*` method resolution,
   `detail_visibility` filtering, all exercised against actual
   plugin code.
2. **Canonical documentation by example.** Third-party plugin
   authors copy this directory as a template. Living
   documentation that can't drift from the implementation.

Layout sketch:

```
test/_plugins/clmail/
  pyproject.toml             # entry-point declarations
  src/claude_code_log_clmail_test/
    __init__.py
    transformers/
      hook_demotion.py       # minimal versions of the four shown above
      communicate.py
  README.md                  # one-page plugin author guide
```

The plugin is installed in editable mode during test setup
(`uv pip install -e test/_plugins/clmail`) so entry-points
resolve at test runtime. Production installs of `claude-code-log`
don't see it; CI does.

## Test strategy

Four layers:

1. **Plugin loader unit tests** (mock entry points via
   `importlib.metadata.entry_points`'s `select(group=...)` and a
   fake EntryPoint object): cover priority ordering, tie-break
   warning, malformed plugin rejection, Protocol-conformance
   rejection.
2. **`_dispatch_format` resolution-order tests**: cover all four
   cells of the resolution matrix (renderer-method only,
   class-method only, both present, neither present). Use the
   embedded reference plugin's classes as fixtures.
3. **Transformer integration tests**: drive a JSONL transcript
   through `claude-code-log` with the embedded reference plugin
   discoverable. Assert transformers fire at correct priorities,
   produced classes flow through `_dispatch_format` to their
   class-side `format_*` methods, `detail_visibility` filters at
   each detail level.
4. **ClMail plugin tests** (in the real `claude-code-log-clmail`
   plugin package, not here): per-action snapshot tests for
   communicate/control/actors/terminal; hook-demotion regression
   tests ported from PR #167's `test_hook_user_notifications.py`.

Snapshot tests for the in-tree built-in renderers (Bash, Read,
WebSearch, ...) need no change — they continue to dispatch via
`format_<ClassName>` on the renderer instance, exactly as today.
The plugin mechanism is purely additive for built-ins.

## Reversal context and trade-offs

The user's pointed question in clmail #3132 reframed the design:

> What if we'd solve the primary need (rendering of generic tools)
> via v2 as well? That is, intercept the generic tool use/result
> messages emitted for `mcp__plugin_clmail_clmail__communicate`
> (and al.) and convert those to specific messages
> (`ClMailToolUse`, `ClMailToolResult`), THEN register parsing
> methods for them.

This collapses the two parallel plugin mechanisms (tool renderers
+ message transformers) of the earlier RFC drafts into one. The
architectural insight: `_dispatch_format` already does MRO walk +
class dispatch, and built-in tools already use specialized
subclasses (`BashInputContent` and friends). The
`winners[tool_name]` table in the earlier RFC was a workaround
for plugins not having method-binding; eliminate the workaround
and one mechanism suffices for both cases.

The trade-offs accepted in adopting unification:

- **v1 surface grows.** Plugins define `MessageContent`
  subclasses, contribute `format_*` / `title` methods on those
  classes, and declare `detail_visibility`. These were all "v2"
  in the earlier RFC; they're "v1" now.
- **Rendering philosophy shifts.** `MessageContent` subclasses
  now know about rendering (via the `format_*` methods they
  carry). Today's classes are pure data. This is a deliberate
  expansion of the class's responsibility, justified by
  symmetry with built-ins and plugin ergonomics.
- **PR #167's eventual migration is no longer deletion-only.**
  Under the existing-variants-only design, migrating #167 to
  a plugin would be a deletion-only refactor in core. Under
  unified-v1, the `UserHookNotificationMessage` class, its
  format/title methods, its CSS, and its tests all move to the
  plugin alongside the matchers. Bigger migration, but
  tractable and one-shot.
- **`detail_visibility` semantics must be pinned in v1.** The
  monotone-down rule (`current_detail >= cls.detail_visibility`)
  and the `_HIGH_EXCLUDE_CLASSES` bridge are part of the v1
  contract.

The earlier "v1 = existing-variants only" landing (commit
`74b5ca6`) was the right answer to a different question (alice
and main both preferred the smaller v1 surface given the
two-mechanism split). The user's #3132 question changes the
shape of the answer: the two-mechanism split was itself the
problem, and collapsing it pays back the surface-area cost in
architectural simplicity.

## Open questions (deferred to implementation)

- **Plugin caching.** Entry-point discovery costs ~10ms on first
  call. If startup profiling shows it, cache the resolved
  transformer list to disk keyed by installed plugin versions.
  Not needed in v1.
- **Plugin enable/disable flag.** `--no-plugin <name>` or env
  var to mask a plugin without uninstalling. Deferred until
  requested.
- **Plugin version pinning.** No machine-readable "requires
  claude-code-log >= X.Y" yet. Use pyproject `requires`; cross
  that bridge when a breaking Protocol change happens.
- **MCP namespace sugar.** Match `clmail__communicate` against
  any `mcp__*__clmail__communicate`. Decline for v1; plugins
  declare exact verbatim tool names. Revisit once we have two
  MCP servers exposing the same tool name.
- **Icon centralization.** Follow-up could migrate scattered
  icon literals (`html/renderer.py:843–930`) into a registry
  populated by plugin classes' icon declarations. v1 keeps
  icons in title methods.
- **Built-in migration to class-method pattern.** Mechanical
  follow-up after v1 lands. Reduces the renderer classes'
  surface area and unifies dispatch. Not blocking.
- **Built-in migration from `_HIGH_EXCLUDE_CLASSES` to
  `detail_visibility`.** Same: mechanical follow-up.
- **Transformer chaining.** First non-None wins in v1; no
  chaining. Revisit only with a concrete use case.
- **Plugin-author docs.** The embedded reference plugin doubles
  as the spec; a `docs/plugin-authoring.md` page may eventually
  formalize it. Defer until external plugins exist.
- **Namespace-collision diagnosis.** No `--list-plugins` CLI in
  v1. Startup warning logs cover the worst case (two transformers
  with same priority and `applies_to`). Follow-up if needed.

## Future extensions

The same entry-point machinery extends cleanly to:

1. **Pluggable formatters.** A new group
   `claude_code_log.formatters` discovers full output formats
   (RTF, JATS, etc.). Discovery, priority, and detail-level
   vocabulary all carry over. A formatter plugin walks the
   `TemplateMessage` tree; classes contribute
   `format_<output_format>` methods for any format they wish to
   support, falling back to "derive from Markdown" for the rest.
2. **Pluggable factories.** Plugins introducing entirely new
   top-level dispatch chains (rather than transforming inside
   an existing one) — e.g. a new entry type the harness might
   emit in future. Much larger surface; not on the near-term
   roadmap.

v1 ships nothing for either future direction; the
`claude_code_log.plugins` entry-point group is scoped narrowly
enough that adding `claude_code_log.formatters` later is purely
additive.
