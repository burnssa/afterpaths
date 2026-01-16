# Afterpaths

**A unified management layer for your AI coding agents.**

You're running Claude Code, Cursor and Codex, but which model actually works best for your stack? What approaches lead to breakthroughs vs. expensive dead ends? How do you stop your agents from making the same mistakes?

Afterpaths gives you a single view across all your AI coding tools: compare what's working, capture discoveries as rules, and guide your agent team away from costly diversions.

## The Problem

You're managing a team of AI coding agents, but flying blind:

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
export ANTHROPIC_API_KEY="sk-ant-..."

# See your recent sessions (Claude Code + Cursor)
ap log

# Get analytics: tokens, sessions, rejection rates
ap stats
ap stats --daily

# Summarize a session (captures discoveries, dead ends, decisions)
ap summarize 1

# Extract rules from summaries → .claude/rules/
ap rules
```

> **Tip:** `ap` is the short alias for `afterpaths`. Both work identically.

See [docs/commands.md](docs/commands.md) for the full command reference and recipes.

## From Session to Rules

**A 2-day auth outage becomes a rule that prevents the next one:**

```markdown
# Dead Ends: What Not to Try

- **Restrictive Auth0 callback detection**: Don't require both 'code' AND
  'state' URL parameters—Auth0 sometimes omits 'state'. This exact pattern
  caused a 2-day production outage. Use `urlParams.has('code')` alone.
  _Source: session 8a3f2c91_

- **Silent callback error handling**: Don't catch Auth0 callback errors and
  redirect to home. Users end up in login loops. Implement error-specific
  recovery logic instead.
  _Source: session 8a3f2c91_
```

Claude Code automatically loads all `.md` files from `.claude/rules/` into context. Next time you're working on auth, Claude already knows what not to try.

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

## The Vault (Coming Soon)

Share and discover rule sets from the community:

```bash
# Install community rules for your stack
afterpaths vault install fastapi-production

# Share your learnings
afterpaths rules publish
```

Popular rule sets surface through community upvotes. Your hard-won discoveries help others avoid the same pitfalls.

## Privacy

- **All local** — Summaries and rules stay in your project
- **Your API key** — Uses your Anthropic/OpenAI key
- **Read-only** — Never modifies your source code
- **Gitignored** — `.afterpaths/` excluded by default
- **Optional sharing** — Vault publishing is explicit opt-in

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
- [ ] Rule Vault (community rule sharing)
- [ ] Semantic search across sessions
- [ ] Benchmarking and productivity insights

## License

MIT

---

*Manage your AI coding agents. Learn what works. Stop repeating mistakes.*
