#!/bin/sh
# Run handgemacht-claude-code-log straight from GitHub — no PyPI, no manual clone.
#
# Usage:
#   ./view.sh ~/path/to/transcript.jsonl --view
#   curl -LsSf https://raw.githubusercontent.com/handgemacht-ai/claude-code-log/main/scripts/view.sh \
#     | bash -s -- ~/transcript.jsonl --view
set -eu

REF="v1.4.0"
REPO="git+https://github.com/handgemacht-ai/claude-code-log@${REF}"

add_uv_paths() {
  for d in "${XDG_BIN_HOME:-}" "${CARGO_HOME:-}/bin" "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    [ -n "$d" ] && [ -d "$d" ] || continue
    case ":$PATH:" in *":$d:"*) ;; *) PATH="$d:$PATH" ;; esac
  done
  export PATH
}

add_uv_paths
if ! command -v uvx >/dev/null 2>&1; then
  echo "uv not found — installing from https://astral.sh/uv ..." >&2
  curl -LsSf https://astral.sh/uv/install.sh | sh
  [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env"
  add_uv_paths
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "ERROR: uv installed but not on PATH. Open a new terminal and re-run." >&2
  exit 1
fi

exec uvx --from "$REPO" handgemacht-claude-code-log "$@"
