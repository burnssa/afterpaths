# Afterpaths

**Smarter with every session, automatically.**

Extract rules from what worked. Track what didn't. Find the best models for your stack.

You're running Claude Code, Cursor and Codex, but which model actually works best for your stack? What approaches lead to breakthroughs vs. expensive dead ends? How do you stop your agents from making the same mistakes?

Afterpaths gives you a single view across all your AI coding tools: compare what's working, capture discoveries as rules, and guide your agent team away from costly diversions.

![Afterpaths Demo](demo.gif)

**What you're seeing:**
1. **`ap audit`** — Overview of your sessions, models used, and rule status
2. **`ap show 5 --raw`** — Raw session transcript (the messy JSONL data, made readable)
3. **`ap show 5`** — LLM-generated summary extracting discoveries, dead ends, and decisions
4. **`head .claude/rules/gotchas.md`** — Rules automatically extracted and ready for Claude's next session

## The Problem

You're managing multiple agents - retaining critical context and learning from sessions is painful:

- **Repeated mistakes** — Your agents hit the same gotchas. Three weeks later, same dead end, same wasted tokens.
- **No cross-tool visibility** — Is Opus actually better than Sonnet for your codebase? Is Cursor outperforming Claude Code? You're guessing.
- **Rules are tedious** — After a costly diversion, the last thing you want is to write a CLAUDE.md rule. So you don't. And the knowledge evaporates.
- **Sessions vanish** — Session content is obscurely logged and hard to extract. Then it's often auto-deleted after 30 days. That breakthrough architecture decision? Context gone.

Afterpaths captures sessions across tools, surfaces what's working, and generates rules automatically—so your agents learn from every session, and you retain all your rich session context.

## How It Works

```
Your Sessions                      Afterpaths
───────────────                    ────────────────────────────────────

Claude Code  ──► ap log      ──► Browse sessions across IDEs
Cursor           ap stats    ──► Analytics: tokens, activity, errors
Codex            ap summarize──► Session summaries (what happened)
                 ap rules    ──► Rule files (what to remember)
                 ap search   ──► Find past discussions & discoveries
                                    │
                                    ▼
                           .claude/rules/ · .cursor/rules/
                                    │
                                    ▼
                           Your next session is smarter
```

## Quick Start

```bash
pip install afterpaths

# Navigate to your project (rules are project-specific)
cd ~/code/your-project

# Run audit to see what you have
ap audit
```

The audit shows your sessions across all tools, model performance, and whether you have rules set up. No API key needed.

**From there, the recommended flow:**

```bash
# 1. Browse sessions and find significant work
ap log

# 2. Summarize important sessions (requires API key)
export ANTHROPIC_API_KEY="sk-ant-..."
ap summarize 1

# 3. Extract rules from summaries → .claude/rules/
ap rules

# 4. Search across past sessions
ap search "database schema"
ap search "auth" --deep    # also search raw transcripts

# 5. Track ongoing performance
ap stats
ap stats --daily
```

> **Tip:** `ap` is the short alias for `afterpaths`. Both work identically.

All commands support `--json` for structured output (e.g., `ap log --json`, `ap show 1 --json`, `ap search "query" --json`).

See [docs/commands.md](docs/commands.md) for the full command reference and recipes.

## From Session to Rules

**Real example: A bug causing 76 missing sessions became a rule that prevents the same mistake.**

While building afterpaths, sessions for a project weren't showing up. The path (let's call it) `/Users/Code/foo_bar` was being decoded as `/Users/Code/foo/bar`. After investigation, we discovered Claude Code uses lossy path encoding—both `/` and `_` become `-`.

**The summary captured the discovery:**

```markdown
## Discoveries

- **Claude Code's path encoding is lossy**: Project paths in `~/.claude/projects/`
  are encoded by replacing `/` with `-`, but underscores are ALSO converted to
  hyphens. Three different paths encode identically:
  - `/Users/Code/foo_bar` → `-Users-Code-foo-bar`
  - `/Users/Code/foo-bar` → `-Users-Code-foo-bar`
  - `/Users/Code/foo/bar` → `-Users-Code-foo-bar`
```

**`ap rules` extracted it into `.claude/rules/gotchas.md`:**

```markdown
- **Claude Code lossy path encoding**: Claude Code encodes project paths by
  replacing both `/` and `_` with `-`, making them indistinguishable when
  decoding. When decoding, try underscore variants alongside hyphen variants
  at each greedy step, preferring longer segments (single directories) over
  nested paths.
  _Source: 91b1ffbc_
```

Next time Claude works on path decoding in this codebase, it already knows about the lossy encoding—no need to rediscover it.

## Why Afterpaths

| Without | With Afterpaths |
|---------|-----------------|
| Discover gotcha, forget to document it | `ap summarize` captures it with full context |
| Hit the same issue 3 weeks later | Rule in `.claude/rules/` prevents it |
| No idea what's working | `ap stats` shows tokens, sessions, error rates |
| Sessions scattered across IDEs | `ap log` unified view across Claude + Cursor |
| Learnings siloed per tool | Rules sync to `.claude/rules/` and `.cursor/rules/` |

## What Gets Extracted

| Category | What it captures | Example |
|----------|------------------|---------|
| **Dead Ends** | Approaches that failed | "Don't use X because Y" |
| **Decisions** | Architectural choices | "We chose Redis over Postgres because..." |
| **Gotchas** | Non-obvious warnings | "Watch out for X when doing Y" |
| **Patterns** | Techniques that worked | "For X, use pattern Y" |

Each rule includes source session references so you can trace back to the original context.

## Supported Tools

| Tool | Status | Location |
|------|--------|----------|
| Claude Code | ✅ Ready | `~/.claude/projects/*.jsonl` |
| Cursor | ✅ Ready | `~/Library/Application Support/Cursor/User/workspaceStorage/` |
| Codex CLI | ✅ Ready | `~/.codex/` |

## MCP Server

Afterpaths includes an MCP server that puts session history directly into your agent's tool list. Instead of relying on agents to discover the CLI, the MCP server makes session search, summaries, and rules available as native tools.

```bash
# Install with MCP support
pip install afterpaths[mcp]

# Add to Claude Code
claude mcp add afterpaths -- afterpaths-mcp

# Or run directly
python -m afterpaths.mcp_server
```

**Tools exposed:**

| Tool | Description |
|------|-------------|
| `afterpaths_list_sessions` | List recent sessions for context recovery |
| `afterpaths_show_session` | Read session summaries and transcripts |
| `afterpaths_summarize` | Generate summaries for sessions |
| `afterpaths_search` | Search across past sessions |
| `afterpaths_get_rules` | Get extracted rules (dead ends, decisions, etc.) |

Once configured, agents can ask "have we seen this before?" or "what were the dead ends?" and get answers from your session history.

## Privacy

- **All local** — Summaries and rules stay in your project
- **Your API key** — Uses your Anthropic/OpenAI key
- **Read-only** — Never modifies your source code
- **Gitignored** — `.afterpaths/` excluded by default

## Storage

```
your-project/
├── .afterpaths/           # Summaries (gitignored)
│   ├── summaries/
│   └── meta.json
├── .claude/
│   └── rules/             # Generated rules (commit these!)
│       ├── dead-ends.md
│       ├── gotchas.md
│       └── patterns.md
└── src/
```

## Roadmap

- [x] Claude Code session parsing
- [x] Cursor session support
- [x] Session analytics (tokens, errors, daily trends)
- [x] LLM summarization
- [x] Automatic rule extraction
- [x] Multi-target export (Claude, Cursor)
- [x] Codex CLI support
- [x] Cross-session search (`ap search`)
- [x] JSON output (`--json` flag)
- [x] MCP server for agent integration
- [ ] Semantic search across sessions
- [ ] Benchmarking and productivity insights

## License

MIT

---

*Manage your AI coding agents. Learn what works. Stop repeating mistakes.*

<!-- mcp-name: io.github.burnssa/afterpaths -->
