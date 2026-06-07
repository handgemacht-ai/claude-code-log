# PR3 design — render the WorkflowRun tree (issue #174, final PR)

Branch: `dev/workflow-tree-render` off main `af7dc29` (PR0+PR1+PR2 landed).
Scope: splice the parsed `WorkflowRun` (phases → agents → each agent's
side-channel transcript) into the message tree at the Workflow tool_use/result
site, on PR0's nested DOM; + snapshot-first header refinement.

## Architecture decisions (locked)

**Strategy B — self-contained sub-tree, spliced post-`_build_message_tree`.**
Do NOT route workflow agents through `_integrate_agent_entries` /
`_build_message_hierarchy` / `_relocate_subagent_blocks` (the 0–5 level-stack
can't express phase→agent→sidechain and the blast radius on non-workflow
rendering is high). Instead build the workflow sub-tree separately and attach
it as `.children` of the Workflow tool_use node after the main tree is built.

### Step 1 — load + link (foundation)
- `converter.load_directory_transcripts`: after the tree is built, call PR1's
  `load_workflow_runs(directory_path)` and stash `{run_id: WorkflowRun}` on the
  `SessionTree` (new field `workflow_runs`, default `{}`).
- `renderer.generate_template_messages`: read `session_tree.workflow_runs`.
- Link each run to its Workflow tool_use: the `runId` is on the tool_RESULT's
  `toolUseResult` (`status: async_launched`), same anchor `_link_async_notifications`
  uses. Find the Workflow `ToolUseMessage` paired with that result; stash the
  `WorkflowRun` on it (e.g. `ToolUseMessage.workflow_run`).

### Step 2 — snapshot-first header (cboos refinement)
- `format_workflow_input` / `MarkdownRenderer.format_WorkflowToolInput`: when a
  linked `WorkflowRun` with a snapshot is present, use its `workflow_name` +
  `phases[].title` for the header (authoritative); else fall back to the
  JS-`meta` regex (`parse_workflow_meta`) for the running/no-snapshot case.
- **Warn** when the JS-meta parse misses expected fields (format-drift signal).
- **Back-fill**: prefer JSON when available; regex is the running-only fallback.

### Step 3 — tree splice (the core)
New `MessageContent` subclasses (in models.py) so they thread into the tree and
dispatch via `format_<ClassName>`:
- `WorkflowPhaseMessage` (title, detail, counts) → phase-header card.
- `WorkflowAgentMessage` (label, model, state, tokens, tool_calls, result) →
  agent card with its result (StructuredOutput dict pygmentized / string md).
Splice pass (after `_build_message_tree`, before render):
- For each Workflow tool_use node with a linked run, synthesize a
  `WorkflowPhaseMessage` TemplateMessage per phase; under each, a
  `WorkflowAgentMessage` per agent; under each agent, the agent's side-channel
  entries rendered into TemplateMessages (reuse the factory→TemplateMessage path
  on `agent.entries`) nested as children. Attach phase nodes as `.children` of
  the tool_use (or tool_result) node.
- Assign `message_index` to synthetic nodes from a high non-colliding counter;
  set `.children` directly (we're past `_build_message_tree`, so ancestry isn't
  needed — just populate `.children` + `message_id`/`should_render`).
- Timeline parity: add the new CSS classes to `components/timeline.html`
  detection.

### Verification
- New fixture already exists: `test/test_data/workflow_basic` (PR1).
- Tests: run discovered+linked; phases/agents/sidechains nested under the
  tool_use; header snapshot-first + warn + fallback; HTML + Markdown.
- Snapshot regen serially (`-n0`); review diff.
- `just ci` green (ty warnings-only/exit-0).

## Open risk
- `message_index` allocation for synthetic nodes must not collide with existing
  indices (anchors/timeline). Use `max(existing)+1...` counter.
- Side-channel entries → TemplateMessages: simplest is a recursive
  `generate_template_messages(agent.entries)` and graft its non-session-header
  nodes; verify it doesn't emit spurious session headers per agent.
