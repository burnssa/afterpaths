# Afterpaths: Feedback from a Claude Code Session

Field notes from a real session where a user asked Claude Code to use `ap summarize` to recover lost context after a context compaction. These observations come from the agent's perspective — what worked, what didn't, and what would make afterpaths a tool agents reach for naturally.

---

## Context: What Happened

Mid-conversation, context compaction wiped out a detailed set of 16 paper recommendations organized across 7 themes. The user asked: "use ap summarize to get the most recent session context with your paper recommendations and build a .md doc I can reference."

The agent:
1. Ran `ap log --all` to find the session
2. Ran `ap summarize` with `--notes` to focus the summary
3. Found the summary useful but incomplete for the specific content needed (paper list was compressed)
4. Had to also spawn a subagent to read the raw JSONL transcript to recover full detail
5. Combined both sources into a reference document

**The user's reaction**: "Why didn't you just use the afterpaths commands? I want to figure out how to make it useful and discoverable for AI agents."

Fair question.

---

## What Worked Well

### Session discovery is excellent
`ap log --all` immediately surfaced the right session by project, date, and size. No fumbling with file paths or guessing at session IDs. This is better than the alternative (grepping through `~/.claude/projects/` directories).

### `--notes` parameter is genuinely useful
Being able to say "focus on the paper recommendations and literature discussion" steered the summary toward relevant content. Without this, the summary would have been even more code/engineering-focused.

### The summary structure is good for engineering context
The default sections (Summary, Discoveries, Dead Ends, Decisions, Gotchas, Open Questions) map well to what an agent needs to resume work. "Dead Ends" is particularly valuable — knowing what was already tried and failed prevents wasted cycles.

### `ap audit` provides useful meta-awareness
Seeing error rates, rejection rates, and model performance across sessions gives context that no individual session provides. An agent could use this to calibrate expectations.

---

## What Fell Short (and Why It Matters for Agent Adoption)

### 1. Summarization compresses conversational content too aggressively

**The problem**: The session contained 16 specific paper recommendations with per-paper relevance descriptions, organized into 7 thematic categories. The summary compressed this into ~8 papers in a short "Literature Positioning" section, losing half the recommendations and all the detailed relevance notes.

**Why this matters for agents**: The #1 reason an agent would use `ap summarize` is to recover *specific* content from a prior session — a code pattern, a decision rationale, a list of recommendations. If the summary loses that specificity, the agent still has to fall back to reading raw transcripts.

**Possible fixes**:
- A `--detail` or `--verbose` flag that preserves lists, tables, and enumerations at full fidelity
- A `--extract` mode that pulls structured content (lists of papers, decisions, code snippets) without narrative compression
- Section-aware summarization that recognizes "this is a list of 16 items" and preserves all 16 rather than sampling

### 2. No way to search across sessions

**The problem**: The agent had to know which session contained the paper recommendations. For this session it was obvious (most recent), but in general an agent might need to find "the session where we discussed database schema options" across dozens of sessions.

**Why this matters for agents**: Agents frequently need to answer "have we discussed X before?" or "what did we decide about Y?" This requires search, not just browse.

**Possible fix**: `ap search "paper recommendations"` or `ap search --keyword "RidgeCV"` that searches across summaries (fast) or raw transcripts (thorough).

### 3. No machine-readable output format

**The problem**: `ap summarize` and `ap show` produce markdown prose. An agent reading this output has to parse natural language to extract structured information. There's no way to get JSON, and no way to request specific sections.

**Why this matters for agents**: Agents work best with structured data. A JSON output with typed fields (`decisions: [{decision, rationale, alternatives_considered}]`, `papers_cited: [{title, authors, relevance}]`) would be directly usable without interpretation overhead.

**Possible fixes**:
- `ap show <session> --json` returning structured summary data
- `ap show <session> --section discoveries` returning just one section
- A structured extraction mode in `ap summarize` that produces JSON alongside the markdown

### 4. No integration with agent memory systems

**The problem**: Claude Code has `~/.claude/projects/<project>/memory/MEMORY.md` for persistent context. Afterpaths has `.afterpaths/summaries/`. These are two parallel systems that don't talk to each other.

**Why this matters for agents**: The agent's memory system is the primary place it looks for persistent context. If afterpaths summaries lived in or were referenced from the memory directory, agents would encounter them naturally.

**Possible fix**: `ap rules` already writes to `.claude/rules/`. Consider also writing a summary index or key findings to the agent's memory location, or at minimum adding a pointer in MEMORY.md like "See afterpaths summaries for session history."

---

## The Critical Path to Agent Adoption: Discoverability

The biggest barrier isn't functionality — it's that **agents don't know afterpaths exists**. Here's the discovery chain and where it breaks:

### How agents currently discover tools

1. **System prompt / tool definitions** — always visible (MCP servers, built-in tools)
2. **CLAUDE.md / project instructions** — loaded every session
3. **Memory files** — checked when relevant
4. **PATH binaries** — only discovered if the agent has reason to look

Afterpaths sits at level 4 — the least discoverable. The agent will never run `ap` unless the user explicitly asks for it or something in levels 1-3 points to it.

### Concrete recommendations for discoverability

**Option A: MCP Server (highest impact)**

Register afterpaths as an MCP server that Claude Code loads automatically. This puts it at level 1 — the agent sees `ap_summarize`, `ap_search`, `ap_log` as available tools in every session. The agent would naturally reach for these when:
- Context gets compacted and information is lost
- The user asks about previous sessions or decisions
- The agent wants to check if a problem was encountered before

This is the single highest-impact change. MCP tools appear in the agent's tool list and have descriptions that trigger usage.

**Option B: Auto-inject into CLAUDE.md or rules (medium impact)**

After `ap rules` runs, also add a brief section to `.claude/rules/` or suggest adding to `CLAUDE.md`:

```markdown
## Session History (afterpaths)
Use `ap log` to browse previous sessions, `ap show <id>` to read summaries,
and `ap summarize <id>` to generate new summaries. Use these to recover
context lost to compaction or to check what was tried previously.
```

This puts afterpaths at level 2 — visible every session via project instructions.

**Option C: Post-session hook (low effort, medium impact)**

Claude Code supports hooks. An afterpaths hook that runs after session end could:
- Auto-summarize long sessions
- Print a one-liner like "Session saved. Use `ap show <id>` to review."
- This creates a breadcrumb trail the *next* agent session might see in terminal history

### The adoption flywheel

The path to distribution through Claude instances:

```
Agent discovers ap exists (MCP / CLAUDE.md mention)
  → Agent uses ap to recover context or check history
    → Agent finds it useful, mentions it in session output
      → User sees value, keeps afterpaths installed
        → ap rules writes guidance that future agents see
          → Future agents use ap more frequently
```

The flywheel stalls at step 1 today. Fix discoverability and the rest follows.

---

## Feature Requests Ranked by Agent Impact

| Priority | Feature | Why |
|----------|---------|-----|
| **P0** | MCP server registration | Agents can't use what they can't see. This is the unlock. |
| **P0** | `ap search` across sessions | "Have we seen this before?" is the most common cross-session question |
| **P1** | `--json` output mode | Agents parse structured data 10x more reliably than prose |
| **P1** | `--verbose` / `--detail` on summarize | Preserve lists and enumerations at full fidelity |
| **P1** | `ap show --section <name>` | Let agents request just what they need |
| **P2** | Auto-summarize hook on session end | Ensures summaries exist without user action |
| **P2** | Memory system integration | Write summary pointers into agent memory directories |
| **P3** | `ap diff <session1> <session2>` | "What changed between these two sessions?" |
| **P3** | `ap context <session> --for-agent` | Produce a compact context block optimized for injection into a new session |

---

## A Note on the Summarization Model

The current summarizer (claude-opus-4-5) produces excellent engineering summaries but is tuned for code-oriented sessions. For research-heavy sessions (like this one, which was 60% discussion about papers and alignment implications, 40% code), the summary under-weights conversational content. Consider:

- Detecting session "type" (code-heavy vs. discussion-heavy vs. mixed) and adjusting the summarization prompt accordingly
- Allowing users to specify summary type: `ap summarize <id> --type research` vs `--type engineering`
- Or simply: when `--notes` mentions specific content to preserve, instruct the summarizer to reproduce that content at full fidelity rather than compressing it

---

## Summary

Afterpaths solves a real problem — context preservation across sessions — but currently requires the user to tell the agent it exists. For a tool whose primary value proposition is making agents smarter, the agent needs to be able to discover and use it independently. An MCP server that surfaces afterpaths commands as first-class tools would transform it from "a CLI the user sometimes remembers to run" into "a persistent memory layer that agents use automatically."

The functionality is already 80% there. The gap is the last mile: discoverability, structured output, and search.
