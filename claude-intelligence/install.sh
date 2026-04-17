#!/bin/bash
# claude-intelligence installer
# Installs hooks, agents, settings, and CLAUDE.md into the current project

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$(pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[claude-intelligence]${NC} $1"; }
success() { echo -e "${GREEN}[claude-intelligence]${NC} $1"; }
warn()    { echo -e "${YELLOW}[claude-intelligence]${NC} $1"; }
error()   { echo -e "${RED}[claude-intelligence]${NC} $1"; exit 1; }

ask_overwrite() {
  local path="$1"
  if [ -f "$path" ]; then
    read -r -p "  '$path' already exists. Overwrite? [y/N] " answer
    case "$answer" in
      [yY][eE][sS]|[yY]) return 0 ;;
      *) warn "Skipping $path"; return 1 ;;
    esac
  fi
  return 0
}

echo ""
echo "  claude-intelligence — Claude Code setup installer"
echo "  Installing into: $TARGET_DIR"
echo ""

# --- Step 1: Check Claude Code is installed ---
if [ ! -d "$HOME/.claude" ]; then
  error "~/.claude/ not found. Install Claude Code first: https://claude.ai/code"
fi
info "Claude Code detected at ~/.claude/"

# --- Step 2: Create .claude/ in cwd ---
mkdir -p "$TARGET_DIR/.claude"
info "Created .claude/"

# --- Step 3: CLAUDE.md ---
if ask_overwrite "$TARGET_DIR/.claude/CLAUDE.md"; then
  cp "$SCRIPT_DIR/templates/CLAUDE.md" "$TARGET_DIR/.claude/CLAUDE.md"
  success "Installed .claude/CLAUDE.md"
  info "  -> Edit .claude/CLAUDE.md: replace {{YOUR_NAME}} and fill in ## Project Context"
fi

# --- Step 4: .claudeignore ---
if ask_overwrite "$TARGET_DIR/.claudeignore"; then
  cp "$SCRIPT_DIR/templates/.claudeignore" "$TARGET_DIR/.claudeignore"
  success "Installed .claudeignore"
fi

# --- Step 5: settings.json ---
if ask_overwrite "$TARGET_DIR/.claude/settings.json"; then
  cp "$SCRIPT_DIR/templates/settings.json" "$TARGET_DIR/.claude/settings.json"
  success "Installed .claude/settings.json"
fi

# --- Step 6: Agents ---
mkdir -p "$TARGET_DIR/.claude/agents"
for agent in "$SCRIPT_DIR/agents/"*.md; do
  name="$(basename "$agent")"
  dest="$TARGET_DIR/.claude/agents/$name"
  if ask_overwrite "$dest"; then
    cp "$agent" "$dest"
    success "Installed .claude/agents/$name"
  fi
done

# --- Step 7: Hooks ---
mkdir -p "$TARGET_DIR/.claude/hooks"
for hook in "$SCRIPT_DIR/hooks/"*; do
  name="$(basename "$hook")"
  dest="$TARGET_DIR/.claude/hooks/$name"
  if ask_overwrite "$dest"; then
    cp "$hook" "$dest"
    # Make shell scripts executable
    if [[ "$name" == *.sh ]]; then
      chmod +x "$dest"
    fi
    success "Installed .claude/hooks/$name"
  fi
done

# --- Step 8: Optional Cohrint API key ---
echo ""
read -r -p "Enter your Cohrint API key (optional, press Enter to skip): " COHRINT_KEY
if [ -n "$COHRINT_KEY" ]; then
  TRACK_FILE="$TARGET_DIR/.claude/hooks/cohrint-track.js"
  if [ -f "$TRACK_FILE" ]; then
    # Insert the key as a fallback in the script (env var still takes precedence)
    sed -i.bak "s|const API_KEY    = process.env.COHRINT_API_KEY   ?? process.env.VANTAGE_API_KEY   ?? '';|const API_KEY    = process.env.COHRINT_API_KEY   ?? process.env.VANTAGE_API_KEY   ?? '$COHRINT_KEY';|" "$TRACK_FILE"
    rm -f "${TRACK_FILE}.bak"
    success "Cohrint API key saved to cohrint-track.js"
    info "  Tip: set COHRINT_API_KEY in your shell profile to override"
  fi
else
  info "Skipped Cohrint API key. Set COHRINT_API_KEY env var to enable cost tracking."
fi

# --- Done ---
echo ""
success "Installation complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit .claude/CLAUDE.md — replace {{YOUR_NAME}} and fill in ## Project Context"
echo "  2. Review .claude/settings.json — adjust permissions for your stack"
echo "  3. Restart Claude Code in this directory"
echo ""
echo "  Agents available (use /agent <name> in Claude Code):"
echo "    code-reviewer  — security, performance, quality review"
echo "    test-writer    — comprehensive test suite generation"
echo "    debugger       — systematic root cause analysis"
echo ""
