# Template Message Children Architecture

This document tracks the exploration of a children-based architecture for `TemplateMessage`, where messages can have nested children to form an explicit tree structure.

## Current Architecture (2025-12-13)

### Data Flow
```
TranscriptEntry[] → generate_template_messages() → root_messages (tree)
                                                          ↓
                    HtmlRenderer._flatten_preorder() → flat_list
                                                          ↓
                              template.render(messages=flat_list)
```

### TemplateMessage (current)
- `generate_template_messages()` returns **tree roots** (typically session headers)
- Each message has `children: List[TemplateMessage]` populated
- `ancestry` field preserved for CSS classes / JavaScript fold/unfold
- HtmlRenderer flattens via pre-order traversal before template rendering

### Hierarchy Levels
```
Level 0: Tree roots (messages without ancestry - typically session headers)
Level 1: User messages
Level 2: Assistant, System, Thinking
Level 3: Tool use/result
Level 4: Sidechain user/assistant/thinking
Level 5: Sidechain tools
```

**Note:** Tree roots are any messages with empty `ancestry`. This is typically session headers, but in degenerate cases (no session headers), user messages or other top-level messages become roots.

### Sidechain Hierarchy Details (2025-12-24)

Sidechain messages come from **Task tool** invocations (subagent spawning). Key findings from investigating real session data:

#### Where Sidechain Children Attach

Due to **pair reordering** (tool_result is moved right after its corresponding tool_use), sidechain messages become children of the **Task tool_result**, not the tool_use.

#### Agent Type Patterns

Real session data shows two distinct patterns depending on agent type:

**Plan-type agents** (e.g., `-Users-dain-workspace-coderabbit-*`):
- Start with a **user prompt** (`UserTextMessage` with `isSidechain=true`, `parentUuid=null`)
- This user prompt duplicates the Task input

Initial tree structure (before cleanup):
```
tool_use (Task)      ← 0 children (pair reordering moves tool_result here)
tool_result (Task)   ← sidechain messages become children here
  └─ user(sc): UserTextMessage    ← Level 4: duplicate of Task input
       └─ assistant(sc)           ← Level 4: parented to user(sc)
       └─ tool_use(sc)            ← Level 5: parented to user(sc)
       └─ tool_result(sc)         ← Level 5
```

After cleanup (user prompt removed, children adopted):
```
tool_result (Task)
  └─ assistant(sc)   ← Now direct child of tool_result
  └─ tool_use(sc)    ← Adopted from removed user(sc)
  └─ tool_result(sc)
```

**Explore-type agents** (e.g., `-src-deep-manifest`):
- Start directly with **assistant** (no user prompt)
- No cleanup needed for the first message

```
tool_result (Task)
  └─ assistant(sc): AssistantTextMessage  ← First child, kept as-is
  └─ tool_use(sc)
  └─ tool_result(sc)
```

#### Child Adoption During Cleanup

When `_cleanup_sidechain_duplicates()` removes a UserTextMessage (the duplicate prompt), it must **adopt the removed message's children** to prevent orphaning Level 5 tool messages:

```python
# In _cleanup_sidechain_duplicates()
if (
    children
    and children[0].is_sidechain
    and isinstance(children[0].content, UserTextMessage)
):
    removed = children.pop(0)
    # Adopt orphaned children (tool_use/tool_result from sidechain)
    if removed.children:
        children[:0] = removed.children
```

Without this adoption, the sidechain tool messages would be lost from the tree.

#### Key Insight

The hierarchy level is determined by message **type**, not by `parentUuid`. A sidechain user message (`parentUuid=null`) still appears at Level 4 because:
1. It has `isSidechain=true`
2. Its effective parent is determined by the Task tool_result (found via timestamp/session matching)
3. The tree-building algorithm correctly places it as a child of the Task tool_result

### Template Rendering (current)
- Single `{% for message in messages %}` loop over flattened list
- Ancestry rendered as CSS classes for JavaScript DOM queries
- Fold/unfold uses `document.querySelectorAll('.message.${targetId}')`
- Tree structure used internally but template still receives flat list

## Future: Recursive Template Rendering

The next step would be to pass tree roots directly to the template and use a recursive macro, eliminating the flatten step.

### Template Rendering (future)
Recursive macro approach (Note: html_content is now passed separately, not stored in message):
```jinja2
{% macro render_message(message, html_content, depth=0) %}
<div class='message {{ message.css_class }}' data-depth='{{ depth }}'>
    <div class='content'>{{ html_content | safe }}</div>
    {% if message.children %}
    <div class='children'>
        {% for child, child_html in message.children_with_html %}
        {{ render_message(child, child_html, depth + 1) }}
        {% endfor %}
    </div>
    {% endif %}
</div>
{% endmacro %}

{% for root, root_html in roots_with_html %}
{{ render_message(root, root_html) }}
{% endfor %}
```

### JavaScript Simplification (future)
With nested DOM structure, fold/unfold becomes trivial:
```javascript
// Hide all children
messageEl.querySelector('.children').style.display = 'none';
// Show children
messageEl.querySelector('.children').style.display = '';
```

This would require updating the fold/unfold JavaScript to work with the nested structure rather than CSS class queries.

## Exploration Log

### Phase 1: Foundation ✅ COMPLETE
- [x] Add `children` field to TemplateMessage (commit `7077f68`)
- [x] Keep existing flat-list behavior working
- [x] Add `flatten()` method for backward compatibility (commit `ed4d7b3`)
  - Instance method `flatten()` returns self + all descendants in depth-first order
  - Static method `flatten_all()` flattens list of root messages
  - Unit tests in `test/test_template_data.py::TestTemplateMessageTree`

### Phase 2: Tree Building ✅ COMPLETE
- [x] Create `_build_message_tree()` function (commit `83fcf31`)
  - Takes flat list with `message_id` and `ancestry` already set
  - Populates `children` field based on ancestry
  - Returns list of root messages (those with empty ancestry)
- [x] Called after `_mark_messages_with_children()` in render pipeline
- [x] Integration tests verify tree building doesn't break HTML generation

### Phase 2.5: Tree-First Architecture ✅ COMPLETE (2025-12-13)
- [x] `generate_template_messages()` now returns tree roots, not flat list (commit `c5048b9`)
- [x] `HtmlRenderer._flatten_preorder()` traverses tree, formats content, builds flat list
- [x] Content formatting happens during pre-order traversal (no separate pass)
- [x] Template unchanged - still receives flat list

**Key insight:** The flat list was being passed to template AND the same messages had children populated. This caused confusion about which structure was authoritative. Now the tree is authoritative and the flat list is derived.

### Phase 3: Template Migration (TODO - Future Work)
- [ ] Create recursive render macro
- [ ] Update DOM structure to use nested `.children` divs
- [ ] Migrate JavaScript fold/unfold to use nested DOM
- [ ] Pass `root_messages` directly to template (eliminate flatten step)

### Challenges & Notes

**Current State (2025-12-13):**
- Tree is the primary structure returned from `generate_template_messages()`
- HtmlRenderer flattens via pre-order traversal for template rendering
- This is cleaner than before: tree in → flat list out (explicit transformation)

**Performance (2025-12-13):**
- Benchmark: 3.35s for 3917 messages across 5 projects
- Pre-order traversal + formatting is O(n)
- No caching needed - each message formatted exactly once

**Why Keep Flat Template (for now):**
1. JavaScript fold/unfold relies on CSS class queries
2. Changing DOM structure requires JS migration
3. Current approach works correctly

## Related Work

### golergka's text-output-format PR
Created `content_extractor.py` for shared content parsing:
- Separates data extraction from presentation
- Dataclasses for extracted content: `ExtractedText`, `ExtractedToolUse`, etc.
- Could be extended for the tree-building approach

### Visitor Pattern Consideration
For multi-format output (HTML, Markdown, JSON), consider:
- TemplateMessage as a tree data structure (no rendering logic)
- Visitor implementations for each output format
- Preparation in converter.py before any rendering
