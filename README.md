# Afterpaths

**Turn painful debugging sessions into permanent wisdom.**

You just spent 2 hours discovering that JWT refresh tokens need a mutex lock. Now you have to manually write a CLAUDE.md rule so Claude doesn't lead you down that path again. You open the file, try to remember the exact context, write something half as good as what you'd get if you captured it in the moment...

Afterpaths does this automatically. Every session. With full context.

## The Problem

When working with Claude Code, Cursor, or Copilot:

- **You repeat mistakes** — Three weeks later, you hit the same gotcha. The AI suggests the same dead end. You vaguely remember solving this before.
- **Sessions disappear** — Claude Code auto-deletes sessions after 30 days. That breakthrough you had last month? Gone. The context that led to your architectural decision? Deleted.
- **Rules are tedious to write** — After a painful discovery, the last thing you want to do is context-switch to writing a CLAUDE.md rule. So you don't. And the knowledge evaporates.
- **Context gets lost** — Even when you do write rules, they're stripped of the rich context: what you tried, why it failed, the specific error messages that led you there.

Afterpaths captures your sessions, extracts the learnings, and generates rules automatically—with all the context intact.

## How It Works

```
Your Sessions                      Afterpaths
───────────────                    ────────────────────────────────────

Claude Code  ──► afterpaths ──► Session summaries (what happened)
Cursor            summarize          │
Copilot                              ▼
                 afterpaths ──► Rule files (what to remember)
                    rules           │
                                    ▼
                              .claude/rules/
                              .cursor/rules/
                                    │
                                    ▼
                           Your next session is smarter
```

## Quick Start

```bash
pip install afterpaths
export ANTHROPIC_API_KEY="sk-ant-..."

# See your recent Claude Code sessions
ap log

# Summarize a session (captures discoveries, dead ends, decisions)
ap summarize 1

# Extract rules from summaries → .claude/rules/
ap rules
```

> **Tip:** `ap` is the short alias for `afterpaths`. Both work identically.

See [docs/commands.md](docs/commands.md) for the full command reference and recipes.

## From Session to Rules

**A 2-hour debugging session becomes:**

```markdown
# Dead Ends: What Not to Try

- **JWT rotation race condition**: Don't use JWT rotation with mobile
  clients—concurrent refresh requests cause race conditions. Use mutex
  locking on the refresh endpoint instead.
  _Source: session 7faf6980_

- **In-memory token cache**: Avoid in-memory caching for auth tokens
  in distributed deployments. Requests hit different instances.
  _Source: session 7faf6980_
```

Claude Code automatically loads all `.md` files from `.claude/rules/` into context at session start—no configuration needed. Next time you're working on auth, Claude already knows what not to try.

## The Manual Way vs Afterpaths

**Without Afterpaths:**
1. Discover painful gotcha after 2 hours
2. Think "I should add this to CLAUDE.md"
3. Get distracted by the actual fix
4. Forget to write the rule
5. Hit the same issue in 3 weeks

**With Afterpaths:**
1. Discover painful gotcha after 2 hours
2. Run `ap summarize 1` (30 seconds)
3. Run `ap rules` (extracts learnings automatically)
4. Rule exists in `.claude/rules/gotchas.md`
5. Claude warns you before you go down that path again

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
| GitHub Copilot | 🔜 Soon | — |

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
- [x] LLM summarization
- [x] Git ref linking
- [x] Automatic rule extraction
- [x] Multi-target export (Claude, Cursor)
- [x] Cursor session support
- [ ] GitHub Copilot support
- [ ] Rule Vault
- [ ] Semantic search across sessions

## License

MIT

---

*Stop losing hard-won knowledge. Let your past sessions guide your future ones.*
