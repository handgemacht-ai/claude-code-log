# Restoring Archived Sessions

When you run `claude-code-log`, you may see output like:

```sh
project-name: cached, 3 archived (0.0s)
```

This indicates that 3 sessions exist in the cache whose source JSONL files have been deleted.

## What Are Archived Sessions?

Archived sessions are sessions preserved in the SQLite cache (`~/.claude/projects/cache.db`) even after their source JSONL files have been deleted. This happens when:

1. Claude Code automatically deletes old JSONL files based on the `cleanupPeriodDays` setting
2. You manually delete JSONL files from `~/.claude/projects/*/`

The cache stores the complete message data, so full restoration is possible.

## Preventing Automatic Deletion

Claude Code automatically deletes session logs after 30 days by default. To change this, add `cleanupPeriodDays` to your `~/.claude/settings.json`:

```json
{
  "cleanupPeriodDays": 99999
}
```

This effectively disables automatic cleanup (274 years). You can also set it to a specific number of days.

See Claude Code's [settings documentation](https://docs.anthropic.com/en/docs/claude-code/settings) for more details.

## Using the TUI to Manage Archived Sessions

The easiest way to browse and restore archived sessions is through the interactive TUI.

### Launch the TUI

```bash
claude-code-log --tui
```

### Toggle Archived View

Press `a` to toggle between current and archived sessions. The header shows the current mode:

```text
┌─ Claude Code Log ─────────────────────────────────────────────────┐
│ Project: my-project ARCHIVED (3)                                  │
│ Sessions: 3 │ Messages: 456 │ Tokens: 45,230                      │
├──────────┬───────────────────────────────────┬─────────┬──────────┤
│ Session  │ Title                             │ Start   │ Messages │
├──────────┼───────────────────────────────────┼─────────┼──────────┤
│ abc123   │ Fix authentication bug            │ 12-01   │ 45       │
│ def456   │ Add user settings page            │ 11-28   │ 123      │
│ ghi789   │ Refactor database layer           │ 11-15   │ 67       │
└──────────┴───────────────────────────────────┴─────────┴──────────┘
 [a] Current  [r] Restore  [h] HTML  [v] View  [q] Quit
```

### Restore a Session

1. Switch to archived view with `a`
2. Navigate to the session you want to restore
3. Press `r` to restore the session to a JSONL file
4. The session will be restored to `~/.claude/projects/{project}/{session-id}.jsonl`
5. Press `a` again to switch back to current sessions and see the restored session

### View Archived Sessions

You can also view archived sessions as HTML or Markdown without restoring them:

- `h` - Open HTML in browser
- `m` - Open Markdown in browser
- `v` - View Markdown in embedded viewer

## Limitations

- **Message order**: Messages are ordered by timestamp, which may differ slightly from original file order for same-timestamp entries
- **Whitespace**: Original JSON formatting is not preserved (semantically identical)

## Manual SQL Approach

For advanced users, you can also query the cache database directly:

```bash
sqlite3 ~/.claude/projects/cache.db
```

```sql
-- List all sessions
SELECT p.project_path, s.session_id, s.first_timestamp, s.message_count
FROM sessions s
JOIN projects p ON s.project_id = p.id
ORDER BY s.first_timestamp;

-- Export a session's messages
SELECT content FROM messages WHERE session_id = 'your-session-id' ORDER BY timestamp;
```
