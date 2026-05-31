# Ghosting epic — implementation plan

> Concrete design for the unified-ghosting refactor that gates D12
> (`detail-delete-reindex`) and the single-axis end-state described in
> [refactor-reindex-with-ghosting.md](refactor-reindex-with-ghosting.md)
> and [simplify-converter-renderer.md §7](simplify-converter-renderer.md#7-detail-filtering-the-single-axis-end-state-added-2026-05-29).

**Status:** AWAITING CBOOS GREENLIGHT. Branched at
`dev/ghosting-epic` from `main` @ `129c998`. No code written yet.

---

## 0. Why this exists

`ctx.messages` is the rendering layer's source-of-truth registry —
every TemplateMessage's `message_index` is its position in this list,
and downstream passes (pair identification, session nav, fork-point
backlinks, junction forward links, hierarchy/tree, fold/unfold) all
read those indices to look things up. Today, two passes
(`_pair_skill_tool_uses` and `_filter_template_by_detail`) **delete**
messages from `ctx.messages`, which invalidates every cached index;
`_reindex_filtered_context` exists solely to rewrite those caches
after the fact.

The remap surface keeps growing — PR #131 added
`SessionHeaderMessage.parent_message_index`, PR #132 added the
async-agents targeted ghost (which proved the alternative works).
Each new index-bearing field is a "remember to remap X" obligation
on every contributor.

The ghosting approach inverts the model: dropped messages stay in
`ctx.messages` (preserving every index), but carry an `is_ghosted`
flag. Downstream passes that *iterate* messages learn to skip
ghosts; passes that read stored indices keep working unchanged. The
two reindex-callers + `_reindex_filtered_context` itself all
disappear once both callers migrate.

This document covers the **entire** migration: the unified flag, the
pass-by-pass changes, the single-axis collapse of pre-render
filtering, and a phased rollout that's reviewable in steps.

---

## 1. Why standalone ghost attempts failed (and the unified version
doesn't)

The verifier rejected two earlier scoped attempts. Both rejections
land on real failure modes that this plan addresses head-on:

### 1.1 `detail-ghost-skill-fold` — "bare card" rendering

**Reject reason:** "the ghosted level-1 slash body adopts the
following assistant turn as a child after `_build_message_hierarchy`,
so the elision rule keeps it (renders a bare card)."

**Root cause:** the existing render-loop elision is `if title or
html or msg.children:` (HTML) — a "no title AND no content AND no
children" rule. A ghost that has visible children is *not* eligible
for elision; it renders as an empty header above its children.

**Why the unified plan fixes it:** `_build_message_hierarchy` learns
to skip ghosts and **graft** their (non-ghost) children to the next
non-ghost ancestor. After hierarchy, a ghost's `children` is empty
(its real children moved up the stack). The existing elision rule
then catches it cleanly — no special case in the render loop.

### 1.2 `detail-move-template-filter-to-tree` — late-pass references

**Reject reason:** "nav/descendant-counts/backlinks run *after* the
proposed prune point, so descendant counts and backlink anchors
would dangle."

**Root cause:** the prior attempt moved the prune (= delete) deeper
into the pipeline without addressing the downstream readers.
Anything that reads stored indices after the prune sees stale
pointers.

**Why the unified plan fixes it:** ghosting **never prunes**. The
indices stay stable across the entire pipeline. Nav, descendant
counts, and backlinks read the same indices they always did; the
only change is that ghost messages' contributions are filtered out
of the *output*, not out of the *registry*.

---

## 2. The unified `is_ghosted` flag

### 2.1 Model

Add one bool to `TemplateMessage` (defined in `renderer.py`):

```python
class TemplateMessage:
    # ... existing fields ...
    self.is_ghosted: bool = False
```

That's the entire model change. No new methods; no per-content-type
flags. Setting `is_ghosted = True` opts the message out of the
*visible* render path while keeping it in every internal index.

### 2.2 Semantics

A ghosted message:

- **Keeps** its `message_index` (so pair-refs, parent_message_index,
  junction_forward_links, session_first_message all stay valid).
- **Keeps** its `meta`, `render_session_id`, `content` (for any pass
  that needs to inspect it, e.g. the `_pair_skill_tool_uses`
  detection scan that runs over `ctx.messages` after ghosts exist).
- **Skipped** by passes that compute *visible* structure:
  `_build_message_hierarchy` (no ancestry contribution, children
  grafted), `_identify_message_pairs` (cannot participate in pairs),
  `_build_message_tree` (not emitted as a root), and the format
  renderers' iteration (not rendered).

### 2.3 Helper

A single helper in `renderer.py`, used by every iterator:

```python
def _visible(messages: Iterable[TemplateMessage]) -> Iterator[TemplateMessage]:
    """Yield only non-ghost messages."""
    return (m for m in messages if not m.is_ghosted)
```

Most passes use `_visible(messages)` instead of `messages` directly.
Where positional lookups are needed (`message_by_index`), the
existing pattern keeps working — ghosts have `message_index` like
anyone else, so the map still resolves; passes that don't WANT to
resolve to a ghost check `if msg.is_ghosted` after the lookup.

---

## 3. Pass-by-pass refactor plan

The pipeline order (from `generate_template_messages`):

| Order | Pass | Today's behavior | Post-ghost behavior |
|---|---|---|---|
| 1 | `_render_messages` | builds `ctx.messages` | unchanged |
| 2 | `_pair_skill_tool_uses` | deletes 1–2 msgs + reindexes | sets `is_ghosted = True`; no reindex |
| 3 | `_link_junction_forwards` | reads ctx.messages + writes indices | unchanged — indices stable |
| 4 | `_filter_template_by_detail` + reindex | deletes many + reindexes | rewritten as `_ghost_template_by_detail(ctx, detail)`; no reindex |
| 5 | `prepare_session_navigation` | reads `ctx.session_first_message` | unchanged |
| 6 | `_reorder_session_template_messages` | reorders by render_session_id | unchanged (ghosts ride along with their session) |
| 7 | `_identify_message_pairs` | sequential pair scan | skips ghosts in adjacency walk AND in indexed pairing |
| 8 | `_reorder_paired_messages` | moves pair_last adjacent | unchanged (ghosts not paired so they don't move) |
| 9 | `_relocate_subagent_blocks` | moves blocks under anchors | unchanged (works on render_session_id / sessionId) |
| 10 | `_build_message_hierarchy` | ancestry from level stack | **skip ghosts + graft children** |
| 11 | `_mark_messages_with_children` | counts via ancestry | naturally correct (ancestry already grafted past ghosts) |
| 12 | `_build_message_tree` | tree by ancestry | skip ghosts from root_messages; children list already excludes them |
| 13 | `_cleanup_sidechain_duplicates` | mutates parent.children | unchanged (already operates on the post-ghost tree) |
| 14 | Format renderers | iterate root_messages → children | naturally exclude ghosts (they're absent from the tree) |

The detailed changes per pass:

### 3.1 `_pair_skill_tool_uses` — set ghosts instead of deleting

Today's tail (line ~3360):

```python
consumed_indices.add(other.message_index)
# ...
kept = [msg for msg in ctx.messages if msg.message_index not in consumed_indices]
_reindex_filtered_context(ctx, kept)
```

After:

```python
consumed_indices.add(other.message_index)
# ...
for msg in ctx.messages:
    if msg.message_index in consumed_indices:
        msg.is_ghosted = True
# No reindex.
```

Same selection logic; the only change is the action.

### 3.2 `_ghost_template_by_detail(ctx, detail)` — replaces filter + reindex

Today (line 730):

```python
if detail != DetailLevel.FULL:
    filtered = _filter_template_by_detail(ctx.messages, detail)
    _reindex_filtered_context(ctx, filtered)
```

After:

```python
if detail != DetailLevel.FULL:
    _ghost_template_by_detail(ctx, detail)  # mutates in place
```

Where `_ghost_template_by_detail` is `_filter_template_by_detail`
with the result-list collection replaced by `msg.is_ghosted = True`.
Same visibility predicate, same `_LOW_KEEP_TOOLS` opt-out, same
sidechain rule — only the side-effect changes.

### 3.3 `_identify_message_pairs` — skip ghosts in BOTH passes

Two places:

1. **`_build_pairing_indices`** (the dict-building first pass): ghost
   messages must NOT be added to the indices. Otherwise an index-based
   pairing could attach a real tool_result to a ghost tool_use.

2. **Sequential scan**: when looking at `messages[i]`,
   `messages[i+1]`, `messages[i+2]` for adjacency, ghosts must be
   skipped. Easiest implementation: iterate `_visible(messages)` and
   keep i/i+1/i+2 as positions in the visible subsequence.

Edge case: a ghost ToolUseMessage with a corresponding non-ghost
ToolResultMessage — the result should NOT be paired (no visible
"use" to pair against), so it just renders as an orphan tool_result.
This is acceptable and matches today's behavior (when the filter
drops the tool_use, the result also drops in most detail levels;
where it doesn't, an orphan tool_result is the correct visible
shape).

### 3.4 `_build_message_hierarchy` — skip ghosts + graft children

The critical pass. Today (line 2148):

```python
for message in messages:
    current_level = ... (from message)
    # pop stack until parent level
    while hierarchy_stack and hierarchy_stack[-1][0] >= current_level:
        hierarchy_stack.pop()
    ancestry = [idx for _, idx in hierarchy_stack]
    if message.message_index is not None:
        hierarchy_stack.append((current_level, message.message_index))
    message.ancestry = ancestry
```

After:

```python
for message in messages:
    if message.is_ghosted:
        # Don't push ghost onto stack: its real children, when they
        # arrive, will compute ancestry against the SURVIVING stack
        # (the ghost's would-be ancestor), naturally grafting up.
        message.ancestry = []  # ghosts have no ancestry of their own
        continue

    current_level = ...
    while hierarchy_stack and hierarchy_stack[-1][0] >= current_level:
        hierarchy_stack.pop()
    ancestry = [idx for _, idx in hierarchy_stack]
    if message.message_index is not None:
        hierarchy_stack.append((current_level, message.message_index))
    message.ancestry = ancestry
```

That's the entire children-grafting mechanism: a ghost never
contributes to the stack, so its children "see through" it to the
next non-ghost ancestor. No explicit graft step needed.

### 3.5 `_mark_messages_with_children` — works for free

Reads ancestry indices, increments counts on ancestors. Since
ancestry now skips ghosts (per 3.4), ghosts naturally don't appear
in any non-ghost message's ancestry — so they're not incremented
*as* parents, and they're not counted *as* children either (per
3.4, ghosts have `ancestry = []` so the `if not message.ancestry`
guard skips them at iteration time).

Optional small change: skip ghosts at the top of the loop for
clarity / a microperf win, but functionally unnecessary.

### 3.6 `_build_message_tree` — exclude ghosts from roots

Today (line 2255):

```python
for message in messages:
    message.children = []
for message in messages:
    if not message.ancestry:
        root_messages.append(message)
    else:
        immediate_parent_index = message.ancestry[-1]
        if immediate_parent_index in message_by_index:
            parent = message_by_index[immediate_parent_index]
            parent.children.append(message)
return root_messages
```

After:

```python
for message in messages:
    if message.is_ghosted:
        message.children = []
        continue  # don't add to roots, don't add as child
    message.children = []
for message in messages:
    if message.is_ghosted:
        continue
    if not message.ancestry:
        root_messages.append(message)
    else:
        immediate_parent_index = message.ancestry[-1]
        if immediate_parent_index in message_by_index:
            parent = message_by_index[immediate_parent_index]
            # parent might be a ghost (its message_index resolved in
            # the map) — but per 3.4 a ghost has ancestry=[] so any
            # non-ghost child's ancestry skips it. Defensive guard:
            if not parent.is_ghosted:
                parent.children.append(message)
```

The defensive guard inside `else` is belt-and-braces — by 3.4's
invariant a non-ghost message's ancestry never names a ghost. But
the guard means the tree-build is correct even if some future code
path violates the invariant.

### 3.7 Format renderers (HTML + Markdown) — no change

The HTML template iterates root_messages and recurses through
`msg.children`. Ghosts are absent from both. The existing "skip
empty messages" elision is no longer needed for ghost-handling
specifically — but stays because it serves other shapes (e.g.
`AwaySummaryMessage` returning `""` at LOW). Net behavior change:
ghosts simply don't exist in the renderer's input. No template
edits.

Markdown is the same — it iterates the same tree.

JSON exporter (`json/renderer.py`) similarly iterates the tree.
Should "just work" — but I'll explicitly verify (see test plan).

### 3.8 `_link_junction_forwards` — unchanged

Reads `ctx.junction_targets` (from session_hierarchy) and
`ctx.messages`. Indices it writes (`junction_forward_links`,
`fork_point_preview`) are stored on real fork-point messages and
reference branch headers by message_index. All indices are stable
under ghosting. No change.

### 3.9 `prepare_session_navigation` — unchanged

Reads `ctx.session_first_message` and emits the nav. All indices
stable. No change.

### 3.10 `_reorder_session_template_messages` — unchanged

Reorders by `render_session_id`. Ghosts have render_session_id
like everyone else, so they ride along with their session and end
up in the reordered list. They'll be invisible in the final output
because the tree-build (3.6) excludes them — but they pass through
this pass unchanged. No change.

### 3.11 `_reorder_paired_messages` — unchanged

Pair fields are not set on ghosts (per 3.3), so they don't move.
The reorder of *real* pairs is unaffected. No change.

### 3.12 `_relocate_subagent_blocks` — unchanged

Operates on `meta.session_id` (the agent sidechain id). Agent
messages aren't typically ghosted by the detail filter (agent
content survives at LOW; sidechain is filtered at MINIMAL but that's
a separate pre-existing path). Even if a ghost is inside a relocated
block, it rides along correctly. No change.

### 3.13 `_cleanup_sidechain_duplicates` — unchanged

Operates on `parent.children` after the tree is built. By 3.6,
`parent.children` doesn't contain ghosts. No change.

---

## 4. The single-axis end-state — delete `_filter_by_detail`
(pre-render)

The pre-render filter (`_filter_by_detail` on `TranscriptEntry`)
exists today only because deleting at the post-render layer needs
the reindex dance. With ghosting, *everything* it does becomes
expressible at the post-render layer via the per-class
`MessageContent.visible_at` predicate.

**Why this is in scope:** ghosting eliminates the cost the pre-render
filter was paying for (avoiding the reindex). Keeping the pre-render
filter after ghosting lands means maintaining two filter axes for
no benefit, exactly the complexity the §7 analysis identifies.

**What goes away:**

- `_filter_by_detail` (renderer.py, called at line 695).
- `application_model.md §2.6`'s two-axis rationale.

**What stays:**

- `_filter_messages` (structural — unrelated to detail level).
- `_LOW_KEEP_TOOLS` (orthogonal tool-name allowlist; lives in the
  same post-render pass that becomes `_ghost_template_by_detail`).

**Net effect on the post-render ghoster:** it gains the
content-item-stripping responsibilities that today live in
`_filter_by_detail`:

- At MINIMAL / USER_ONLY: strip `ThinkingContent`, `ToolUseContent`,
  `ToolResultContent` from each surviving message's content.
- At LOW: strip `ThinkingContent`.
- At HIGH: drop system entries except `away_summary`.

Each strip rule is naturally expressible on the post-render
TemplateMessage: ToolUseMessage / ToolResultMessage / ThinkingMessage
already have their own classes; the strip becomes
`msg.is_ghosted = True` for the class. (Effectively: the per-class
`detail_visibility` declarations already encode these rules — see
[plugins.md §6](../dev-docs/plugins.md) — so the pre-render strip
collapses into the post-render visibility predicate.)

The one wrinkle: a single transcript entry can produce multiple
TemplateMessages (e.g., an assistant turn with text + tool_use →
AssistantTextMessage + ToolUseMessage). Pre-render filtering at
MINIMAL would strip the tool_use content item before factory
dispatch, leaving only the text → factory emits only
AssistantTextMessage. Post-render ghosting keeps both messages but
ghosts the ToolUseMessage. The visible output is identical (a single
AssistantTextMessage). The CHUNK_BOUNDARIES are slightly different
in intermediate `ctx.messages`, but since the renderer iterates
the tree (post-ghost), the rendered output matches.

**Risk:** the chunk-boundary difference could change `message_index`
values for surviving messages. Snapshots that ASSERT specific indices
(unusual; mostly snapshots assert rendered HTML/MD) would change.
This needs verification when the single-axis collapse lands —
likely Phase 3 of the rollout.

---

## 5. Phased rollout

The whole epic in one PR would be too big and too risky. Three
phases, each a separate PR, each independently merge-able:

### Phase 1 — `wf/ghosting/skill-fold` (small, safe)

- Add `TemplateMessage.is_ghosted = False`.
- Migrate `_pair_skill_tool_uses` to set `is_ghosted` instead of
  deleting + reindexing.
- Implement steps 3.4 (hierarchy graft) and 3.6 (tree skip ghosts)
  — both are needed for the Skill ghost to render correctly.
- Implement step 3.3 (pair-id skip ghosts) — defensive; the Skill
  ghosts aren't paired but the next phase needs this.
- Leave `_filter_template_by_detail` and its reindex call
  unchanged.
- Leave `_reindex_filtered_context` in place (still called by the
  detail filter path).
- Verify: full suite green (1924 prior), snapshot byte-identity
  expected. Pin a Skill-fold-on-a-fork test (the PR #131 regression
  origin), at FULL detail. This is the test the verifier called out
  as missing for D12; landing it in Phase 1 closes the gate
  prerequisite even before the detail-filter migration.

Estimate: ~150 lines net change. Lowest risk; lays the
infrastructure.

### Phase 2 — `wf/ghosting/detail-filter` (medium)

- Migrate `_filter_template_by_detail` + reindex to
  `_ghost_template_by_detail` (set `is_ghosted` instead of deleting).
- Delete `_reindex_filtered_context` (no more callers).
- Re-run per-detail-level snapshot suite. EXPECTED:
  byte-identical (ghosting produces the same visible output as
  deleting + reindexing, by construction).
- If any snapshot moves: it's a bug, not an intentional change —
  investigate before regenerating.

Estimate: ~200 lines net change (mostly deletion of
`_reindex_filtered_context` and its callers' tail). This is the D12
deletion itself.

### Phase 3 — `wf/ghosting/single-axis-collapse` (the §7 end-state)

- Move the pre-render strip rules from `_filter_by_detail` into
  the post-render ghoster's per-class predicate (`detail_visibility`
  ClassVars already cover most of it; one or two cases may need a
  small tweak).
- Delete `_filter_by_detail` and its call.
- Verify: snapshots may move by chunk-boundary effects (see §4
  wrinkle); review and regenerate IF the rendered output is
  byte-identical and ONLY the intermediate indices shifted.

Estimate: ~150 lines deletion (the pre-render filter is ~80 lines)
plus a handful of `detail_visibility` reconciliations. Highest
risk because of the chunk-boundary edge.

Phases 1 + 2 together delete `_reindex_filtered_context`. Phase 3
is the bonus single-axis cleanup; if it surfaces a deeper issue, it
can be deferred indefinitely without holding up D12 (which is
Phase 1 + 2's combined effect).

---

## 6. Test strategy

### 6.1 What MUST stay green

- Full unit suite (currently 1924 passed, 7 skipped).
- HTML + Markdown snapshot suites — byte-identical across Phase 1
  and Phase 2.
- All five `--detail` level snapshots — byte-identical across Phase
  1 and Phase 2.
- `test_skill_pairing.py::TestReindexBranchBackrefs` — the PR #131
  regression test. Currently runs at non-FULL detail (the only path
  that triggers reindex pre-ghosting). After Phase 1, the equivalent
  invariant must be exercised at FULL detail (Phase 1 ghosts inside
  the Skill-fold path which runs unconditionally).
- `test_dag_integration.py::TestRenderSessionResetAcrossSessions`
  (the latent-bug regression from D11) — independent of ghosting,
  should be entirely unaffected.

### 6.2 New tests added in Phase 1

1. **Skill-fold-on-a-fork at FULL detail** (the test the verifier
   called out as missing): construct a fixture with a Skill spawn
   inside a within-session branch; render at FULL; assert the
   branch's `parent_message_index` points to the correct fork
   anchor, the ghosted slash-command body is absent from the
   rendered output, AND the branch backlink "from #msg-d-{N}"
   resolves to the right anchor. This is the test the verifier
   identified as missing for D12 — landing it in Phase 1 means
   D12 (Phase 2 in this plan) inherits coverage.

2. **Skill-fold ghost doesn't break pairing**: a Skill `tool_use`
   inside a session where the slash-body has been ghosted should
   still pair correctly with its matching `tool_result` (if not
   also ghosted by the launching-skill payload rule).

3. **Ghost-with-children graft**: synthetic fixture where a
   ToolUseMessage (ghosted at MINIMAL) has children (a sidechain
   subagent thread that survives); assert the children's ancestry
   resolves to the ghost's *parent*, not the ghost itself.

### 6.3 New tests added in Phase 2

1. **Detail-filter byte-identity**: parametrize over every
   `DetailLevel` value, render a complex fixture (the existing
   per-detail snapshot fixture), assert the rendered output is
   byte-identical to the pre-Phase-2 baseline. This is the
   structural-correctness pin for the deletion.

2. **`_reindex_filtered_context` deleted**: grep -based static
   check that the symbol no longer exists (catches accidental
   re-introduction).

### 6.4 Failing-on-pre-ghosting verification

Per the D11 pattern: each phase's pinning test should FAIL on the
pre-phase tip when applied as a patch (in a `/tmp` throwaway
worktree). This proves the test genuinely exercises the new
behavior, not just passes vacuously.

---

## 7. Risks

### 7.1 Hidden index reader

Some pass we haven't catalogued might read `len(ctx.messages)` or
iterate `ctx.messages` and assume no ghosts. Mitigation:
`_visible(...)` helper in the renderer + targeted code-review of
the full `renderer.py` (find every `ctx.messages` reference) before
Phase 1 lands.

### 7.2 Memory bloat

Ghosts stay in memory. The pre-render filter at MINIMAL drops the
most messages (no tools, no thinking, no sidechain), often the
majority of a long transcript. Keeping them in `ctx.messages` could
~triple peak memory at MINIMAL for huge transcripts. Mitigation:
acceptable for the dominant use case (transcripts in the
single-MB-to-tens-of-MB range); revisit if a profiling pass shows
real-world peak going past 1 GB.

### 7.3 Markdown chunk-boundary subtlety (Phase 3 only)

When a single transcript entry's content items are split into
multiple TemplateMessages, pre-render filtering keeps factory
boundaries; post-render ghosting keeps the *ghosted* messages and
may shift downstream indices. The rendered output should be
identical (the tree iteration skips ghosts), but `d-{index}`
anchors may move. If a snapshot's `d-{N}` references shift, the
HTML is "different bytes, same logical content" — needs careful
review per snapshot.

### 7.4 Plugin contract

Third-party `MessageContent` subclasses interact with ghosting only
via `is_ghosted` (or not at all, since they don't set it). Their
`visible_at` predicate continues to drive whether they get ghosted,
identical to today. No plugin-contract change.

---

## 8. Rollout decisions for cboos to make

1. **Approve the phased plan** (Phases 1 + 2 + 3 as separate PRs)
   vs. monolithic.
2. **Approve dropping `_filter_by_detail`** (Phase 3 / single-axis
   collapse) vs. leaving the two-axis structure in place.
3. **Approve the Phase 1 "Skill-fold on a fork at FULL detail" test**
   as the D12 prerequisite, even though it lands in Phase 1.
4. **Allocate review:** monk reviews each phase; main coordinates;
   cboos merges.

Once approved, I'll start with Phase 1 on a new branch
`wf/ghosting/skill-fold` from `main` (this `dev/ghosting-epic`
branch is just the planning scratchpad — its only commit will be
this doc).

---

## 9. Pointers

- [refactor-reindex-with-ghosting.md](refactor-reindex-with-ghosting.md)
  — the original problem statement.
- [simplify-converter-renderer.md §3 opp 12 + §6 + §7](simplify-converter-renderer.md)
  — D12 gate context, verifier rejections, single-axis end-state.
- [dev-docs/rendering-architecture.md](../dev-docs/rendering-architecture.md)
  — the pipeline overview.
- [dev-docs/plugins.md §6](../dev-docs/plugins.md) — per-class
  `detail_visibility` mechanism.
- [PR #131](https://github.com/daaain/claude-code-log/pull/131) +
  [PR #132](https://github.com/daaain/claude-code-log/pull/132)
  — the regressions that motivated the epic.
