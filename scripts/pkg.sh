#!/usr/bin/env bash
# pkg.sh — npm package helper for build, test locally, and publish
# Works from any package dir or pass the package path as an argument.
#
# Usage:
#   ./scripts/pkg.sh <command> [package-dir] [options]
#
# Commands:
#   login                   npm login (interactive)
#   build [dir]             Build the package
#   link [dir]              npm link for local testing (global install from source)
#   unlink [dir]            Remove the global link
#   pack [dir]              Create tarball for local install testing
#   install-local [dir]     Install tarball into current project (for testing)
#   publish [dir] [bump]    Build, bump version, publish (bump: patch|minor|major)
#   status [dir]            Show package name, version, npm login, link status
#
# Examples:
#   ./scripts/pkg.sh status vantage-cli
#   ./scripts/pkg.sh link vantage-cli          # global install from source
#   ./scripts/pkg.sh publish vantage-cli patch  # bump patch, build, publish
#   ./scripts/pkg.sh pack vantage-cli          # create .tgz for testing

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
DIM='\033[2m'
RESET='\033[0m'

info()  { echo -e "${GREEN}[pkg]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[pkg]${RESET} $*"; }
err()   { echo -e "${RED}[pkg]${RESET} $*" >&2; }
dim()   { echo -e "${DIM}$*${RESET}"; }

# Resolve project root (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Resolve package directory
resolve_pkg() {
  local dir="${1:-}"
  if [[ -z "$dir" ]]; then
    # Use current directory if it has package.json
    if [[ -f "package.json" ]]; then
      pwd
      return
    fi
    err "No package directory specified and no package.json in current dir"
    exit 1
  fi
  # Absolute or relative to project root
  if [[ -d "$dir" && -f "$dir/package.json" ]]; then
    cd "$dir" && pwd
  elif [[ -d "$ROOT/$dir" && -f "$ROOT/$dir/package.json" ]]; then
    cd "$ROOT/$dir" && pwd
  else
    err "Not a package directory: $dir"
    exit 1
  fi
}

pkg_name() { node -e "console.log(require('./package.json').name)"; }
pkg_version() { node -e "console.log(require('./package.json').version)"; }

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_login() {
  if npm whoami 2>/dev/null; then
    info "Already logged in as $(npm whoami)"
  else
    info "Opening npm login..."
    npm login
  fi
}

cmd_status() {
  local pkg_dir
  pkg_dir="$(resolve_pkg "${1:-}")"
  cd "$pkg_dir"

  local name version
  name="$(pkg_name)"
  version="$(pkg_version)"

  echo ""
  info "Package:  $name"
  info "Version:  $version"
  info "Dir:      $pkg_dir"

  # npm login
  if npm whoami 2>/dev/null >/dev/null; then
    info "npm user: $(npm whoami)"
  else
    warn "npm:      not logged in"
  fi

  # Published version
  local published
  published="$(npm view "$name" version 2>/dev/null || echo "not published")"
  info "Published: $published"

  # Global link
  local link_target
  link_target="$(npm ls -g --link --json 2>/dev/null | node -e "
    const d=require('fs').readFileSync('/dev/stdin','utf8');
    const j=JSON.parse(d);
    const deps=j.dependencies||{};
    const match=Object.entries(deps).find(([k])=>k==='$name');
    console.log(match ? 'linked -> '+match[1].resolved : 'not linked');
  " 2>/dev/null || echo "not linked")"
  info "Global:    $link_target"
  echo ""
}

cmd_build() {
  local pkg_dir
  pkg_dir="$(resolve_pkg "${1:-}")"
  cd "$pkg_dir"

  info "Building $(pkg_name)@$(pkg_version) ..."
  npm run build
  info "Build complete."
}

cmd_link() {
  local pkg_dir
  pkg_dir="$(resolve_pkg "${1:-}")"
  cd "$pkg_dir"

  info "Building before link..."
  npm run build

  info "Linking $(pkg_name) globally..."
  npm link
  info "Linked. Run '$(node -e "console.log(Object.keys(require('./package.json').bin||{})[0]||require('./package.json').name)")' from anywhere."
}

cmd_unlink() {
  local pkg_dir
  pkg_dir="$(resolve_pkg "${1:-}")"
  cd "$pkg_dir"

  local name
  name="$(pkg_name)"
  info "Unlinking $name..."
  npm unlink -g "$name" 2>/dev/null || npm rm -g "$name" 2>/dev/null || true
  info "Unlinked."
}

cmd_pack() {
  local pkg_dir
  pkg_dir="$(resolve_pkg "${1:-}")"
  cd "$pkg_dir"

  info "Building before pack..."
  npm run build

  info "Creating tarball..."
  local tarball
  tarball="$(npm pack 2>&1 | tail -1)"
  info "Created: $pkg_dir/$tarball"
  echo ""
  dim "Install in another project with:"
  dim "  npm install $pkg_dir/$tarball"
}

cmd_install_local() {
  local pkg_dir
  pkg_dir="$(resolve_pkg "${1:-}")"
  cd "$pkg_dir"

  info "Building $(pkg_name)..."
  npm run build

  local tarball
  tarball="$(npm pack 2>&1 | tail -1)"

  info "Installing $pkg_dir/$tarball into current project..."
  cd "$ROOT"
  npm install "$pkg_dir/$tarball"
  info "Installed locally for testing."
}

cmd_publish() {
  local pkg_dir bump
  pkg_dir="$(resolve_pkg "${1:-}")"
  bump="${2:-}"
  cd "$pkg_dir"

  local name
  name="$(pkg_name)"

  # Check login
  if ! npm whoami 2>/dev/null >/dev/null; then
    err "Not logged in. Run: ./scripts/pkg.sh login"
    exit 1
  fi
  info "Logged in as $(npm whoami)"

  # Check clean git state for the package dir
  local changes
  changes="$(cd "$ROOT" && git diff --name-only HEAD -- "$(basename "$pkg_dir")/" 2>/dev/null || true)"
  if [[ -n "$changes" ]]; then
    warn "Uncommitted changes in $(basename "$pkg_dir"):"
    dim "$changes"
    echo ""
    read -rp "Continue anyway? [y/N] " confirm
    [[ "$confirm" =~ ^[yY] ]] || exit 1
  fi

  # Version bump
  if [[ -n "$bump" ]]; then
    info "Bumping version ($bump)..."
    npm version "$bump" --no-git-tag-version
    info "New version: $(pkg_version)"
  fi

  # Build
  info "Building..."
  npm run build

  # Publish
  local version
  version="$(pkg_version)"
  info "Publishing $name@$version..."
  npm publish --access public

  info "Published $name@$version"
  echo ""
  dim "Install with: npm install -g $name@$version"
}

# ── Main ──────────────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
pkg.sh — npm package helper for build, test locally, and publish

USAGE
  ./scripts/pkg.sh <command> [package-dir] [options]

ARGUMENTS
  package-dir   Path to the package (relative to project root or absolute).
                If omitted, uses the current directory (must contain package.json).
                Examples: vantage-cli, vantage-mcp, vantage-js-sdk

COMMANDS
  login                              Log in to npm registry (interactive).
                                     No arguments needed.

  status [dir]                       Show package name, version, published version,
                                     npm login status, and global link status.

  build [dir]                        Run `npm run build` in the package directory.

  link [dir]                         Build the package, then `npm link` to make it
                                     available globally from source. Use this to test
                                     CLI tools locally (e.g. `vantage` command).

  unlink [dir]                       Remove the global npm link for the package.

  pack [dir]                         Build and create a .tgz tarball. Useful for
                                     installing into other projects without publishing:
                                       npm install /path/to/package-1.0.0.tgz

  install-local [dir]                Build, pack, and install the tarball into the
                                     project root. Simulates a real npm install for
                                     integration testing.

  publish [dir] [patch|minor|major]  Build and publish to npm registry.
                                     If a bump type is given, bumps version first:
                                       patch  1.0.0 → 1.0.1
                                       minor  1.0.0 → 1.1.0
                                       major  1.0.0 → 2.0.0
                                     If omitted, publishes the current version as-is.
                                     Requires npm login. Warns on uncommitted changes.

EXAMPLES
  ./scripts/pkg.sh status vantage-cli
      Show vantage-cli package info and registry status.

  ./scripts/pkg.sh link vantage-cli
      Build and globally link so `vantage` command uses local source.

  ./scripts/pkg.sh unlink vantage-cli
      Remove the global link.

  ./scripts/pkg.sh pack vantage-mcp
      Create vantage-mcp-1.1.1.tgz for local testing.

  ./scripts/pkg.sh publish vantage-cli patch
      Bump 2.2.5 → 2.2.6, build, and publish to npm.

  ./scripts/pkg.sh publish vantage-js-sdk
      Publish current version without bumping.

WORKFLOW — Local Testing
  1. ./scripts/pkg.sh link vantage-cli       # global install from source
  2. vantage --help                          # test the CLI
  3. # make code changes...
  4. ./scripts/pkg.sh build vantage-cli      # rebuild
  5. vantage --help                          # test again (link auto-updates)
  6. ./scripts/pkg.sh unlink vantage-cli     # cleanup when done

WORKFLOW — Publish a Release
  1. ./scripts/pkg.sh login                  # ensure logged in
  2. ./scripts/pkg.sh status vantage-cli     # check current state
  3. ./scripts/pkg.sh publish vantage-cli patch  # bump + publish
EOF
}

cmd="${1:-}"
shift || true

case "$cmd" in
  login)         cmd_login ;;
  status)        cmd_status "$@" ;;
  build)         cmd_build "$@" ;;
  link)          cmd_link "$@" ;;
  unlink)        cmd_unlink "$@" ;;
  pack)          cmd_pack "$@" ;;
  install-local) cmd_install_local "$@" ;;
  publish)       cmd_publish "$@" ;;
  -h|--help|"")  usage ;;
  *)             err "Unknown command: $cmd"; usage; exit 1 ;;
esac
