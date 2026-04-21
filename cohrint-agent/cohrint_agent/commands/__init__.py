"""
commands — per-verb subcommand implementations.

Each module exports a ``run(argv: list[str]) -> int`` entrypoint. The argv
slice starts AFTER the verb (so ``cohrint-agent mcp list --backend claude``
reaches ``commands.mcp.run(["list", "--backend", "claude"])``).

The catalog below is the single source of truth for ``/help`` and
``cohrint-agent <verb> --help`` — both render from it. Do not hand-write
help text in individual command modules; extend this catalog instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VerbSpec:
    """One top-level verb (mcp, skills, agents, hooks, ...)."""

    name: str
    summary: str
    subcommands: dict[str, str] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)


# ──────────────── catalog (rendered in /help, --help, docs.html) ────────────
CATALOG: dict[str, VerbSpec] = {
    "models": VerbSpec(
        name="models",
        summary="List supported models across all backends.",
        subcommands={
            "": "Print the full list grouped by backend.",
            "--unsupported": "Show models routed but not priced.",
            "info <id>": "Single-model detail (pricing, tier, backend).",
        },
        examples=[
            "cohrint-agent models",
            "cohrint-agent models info claude-opus-4-6",
        ],
    ),
    "mcp": VerbSpec(
        name="mcp",
        summary="Manage MCP servers across claude / gemini / codex.",
        subcommands={
            "list [--backend X]": "List MCP servers (default: all backends).",
            "list -i": "Interactive selector — press Enter to see detail.",
            "add NAME --command CMD [--arg A]": "Register a stdio MCP server.",
            "add NAME --url URL": "Register a remote (HTTP) MCP server.",
            "remove NAME [--backend X]": "Unregister an MCP server.",
        },
        examples=[
            "cohrint-agent mcp list",
            "cohrint-agent mcp add weather --command npx --arg -y --arg weather-mcp",
            "cohrint-agent mcp remove weather --backend claude",
        ],
    ),
    "plugins": VerbSpec(
        name="plugins",
        summary="Manage Claude Code plugins (claude-only).",
        subcommands={
            "list": "List enabled plugins. Empty for non-claude backends.",
            "enable NAME": "Flip enabledPlugins[NAME] to true.",
            "disable NAME": "Flip enabledPlugins[NAME] to false.",
        },
        examples=[
            "cohrint-agent plugins list",
            "cohrint-agent plugins enable formatter@anthropic-tools",
        ],
    ),
    "skills": VerbSpec(
        name="skills",
        summary="Manage skills (Claude skills + Codex rules).",
        subcommands={
            "list [--backend X]": "List skills across global + project dirs.",
            "add PATH [--name N] [--backend X]": "Install a skill from a local path.",
            "remove NAME [--backend X]": "Delete a skill.",
        },
        examples=[
            "cohrint-agent skills list",
            "cohrint-agent skills add ./my-skill",
            "cohrint-agent skills remove my-skill",
        ],
    ),
    "agents": VerbSpec(
        name="agents",
        summary="Manage sub-agents (Claude agents/*.md).",
        subcommands={
            "list [--backend X]": "List available agents.",
            "add PATH [--name N]": "Install an agent .md.",
            "remove NAME": "Delete an agent.",
        },
        examples=[
            "cohrint-agent agents list",
            "cohrint-agent agents add ./reviewer.md",
        ],
    ),
    "hooks": VerbSpec(
        name="hooks",
        summary="Manage hooks in settings.json.",
        subcommands={
            "list": "Print every hook grouped by event + matcher.",
            "add EVENT MATCHER CMD": "Append a command-type hook.",
            "remove EVENT MATCHER": "Drop hooks matching EVENT[MATCHER].",
        },
        examples=[
            "cohrint-agent hooks list",
            'cohrint-agent hooks add PostToolUse "Write|Edit" "prettier --write"',
        ],
    ),
    "permissions": VerbSpec(
        name="permissions",
        summary="Manage allow/deny/ask rules in settings.json.",
        subcommands={
            "list": "Print every permission rule grouped by kind.",
            "allow RULE": "Add RULE to permissions.allow.",
            "deny RULE": "Add RULE to permissions.deny.",
            "ask RULE": "Add RULE to permissions.ask.",
            "remove KIND RULE": "Remove RULE from KIND bucket.",
        },
        examples=[
            "cohrint-agent permissions allow 'Bash(npm *)'",
            "cohrint-agent permissions deny 'Bash(rm -rf *)'",
        ],
    ),
    "settings": VerbSpec(
        name="settings",
        summary="View + mutate merged settings.json.",
        subcommands={
            "show": "Pretty-print merged settings JSON.",
            "set KEY VALUE": "Set a dotted key (value coerced to bool/int/JSON/str).",
        },
        examples=[
            "cohrint-agent settings show",
            "cohrint-agent settings set model claude-opus-4-6",
            "cohrint-agent settings set permissions.defaultMode acceptEdits",
        ],
    ),
    "init": VerbSpec(
        name="init",
        summary="Scaffold cohrint tooling in the current project (append-safe).",
        subcommands={
            "": "Add a cohrint block to CLAUDE.md + create .claude/settings.local.json.",
            "--force": "Overwrite an existing cohrint block.",
        },
        examples=["cohrint-agent init", "cohrint-agent init --force"],
    ),
    "guardrails": VerbSpec(
        name="guardrails",
        summary="Toggle recommendation / hallucination guardrails.",
        subcommands={
            "status": "Show current guardrail settings.",
            "on [KIND]": "Enable a guardrail (KIND = recommendation|hallucination|all).",
            "off [KIND]": "Disable a guardrail.",
        },
        examples=[
            "cohrint-agent guardrails status",
            "cohrint-agent guardrails on hallucination",
            "cohrint-agent guardrails off all",
        ],
    ),
    "exec": VerbSpec(
        name="exec",
        summary="Run a backend CLI subcommand directly (passthrough).",
        subcommands={
            "<backend> <args...>": "execvp into `<backend> <args...>`.",
        },
        examples=[
            "cohrint-agent exec claude mcp add foo --command ./bar",
            "cohrint-agent exec gemini init",
        ],
    ),
}

VERBS = tuple(CATALOG.keys())


def render_catalog() -> str:
    """Human-readable catalog string. Used by /help and --help."""
    lines: list[str] = []
    lines.append("cohrint-agent — AI coding agent with multi-backend tooling\n")
    lines.append("Verbs:")
    for verb in CATALOG.values():
        lines.append(f"  {verb.name:<12} {verb.summary}")
    lines.append("")
    lines.append("Per-verb help:  cohrint-agent <verb> --help")
    lines.append("Docs:           https://cohrint.com/docs#cli-reference")
    return "\n".join(lines)


def render_verb_help(verb: str) -> str:
    """Render `<verb> --help` output."""
    spec = CATALOG.get(verb)
    if spec is None:
        return f"unknown verb '{verb}'"
    lines: list[str] = [f"cohrint-agent {verb} — {spec.summary}", ""]
    if spec.subcommands:
        lines.append("Subcommands:")
        for sub, desc in spec.subcommands.items():
            key = f"{verb} {sub}".strip()
            lines.append(f"  {key:<32} {desc}")
        lines.append("")
    if spec.examples:
        lines.append("Examples:")
        for ex in spec.examples:
            lines.append(f"  {ex}")
    return "\n".join(lines)


__all__ = ["CATALOG", "VERBS", "VerbSpec", "render_catalog", "render_verb_help"]
