# Understanding Your Stats

Afterpaths shows daily usage statistics on your first command each day. This guide explains what each metric means and how to interpret them.

## Daily Stats Display

On first use each day, you'll see a summary like this:

```
╭─ Your Stats ─────────────────────────────────────────────────────────╮
│                                                                      │
│  Yesterday                                                           │
│    Sessions: 3   Messages: 175   Tool calls: 99                      │
│    claude-opus-4: Rejections 0 (0.0%)  Failures 2 (2.0%)             │
│                                                                      │
│  Last 7 Days                                                         │
│    Sessions: 14  Messages: 3747  Tool calls: 2267                    │
│    claude-opus-4: Rejections 14 (0.6%)  Failures 136 (6.0%)          │
│                                                                      │
│  IDE Used: Claude Code                                               │
│  Stack Used: python, react                                           │
│  Platform: macOS                                                     │
│  Peak Hours: 15:00, 10:00, 12:00                                     │
│                                                                      │
╰──────────────────────────────────────────────────────────────────────╯
```

## Time Periods

**Yesterday**: The previous calendar day (midnight to midnight in your local timezone). This gives you a complete picture of your most recent full day of work.

**Last 7 Days**: Yesterday plus the 6 days before it. This provides trend data to compare against daily fluctuations.

Why not "today"? Today's stats would be incomplete until the day ends, making comparisons misleading.

## Metrics Explained

### Sessions

A session is a single conversation with an AI coding assistant. Each time you start a new conversation in Claude Code (or other supported tools), that's one session.

- **Main sessions**: Regular conversations you initiate
- **Agent sessions**: Sub-processes spawned by the Task tool (filtered out by default)

### Messages

Total count of user and assistant messages exchanged. Higher counts generally indicate longer, more involved coding sessions.

### Tool Calls

The number of times the AI invoked tools (Edit, Write, Bash, Read, etc.) during your sessions. This measures how much "hands-on" work the AI performed.

### Rejections vs Failures

These are the key quality metrics for understanding AI tool performance:

| Metric | What It Means | Common Causes |
|--------|---------------|---------------|
| **Rejections** | Tool was called but user declined to run it | Permission denied, user canceled, sandbox restrictions |
| **Failures** | Tool ran but returned an error | Syntax errors, file not found, command failed, runtime errors |

**Rejection rate** = Rejections / Total tool calls × 100

A rejection happens when the AI attempts an action that gets blocked before execution. Common scenarios:
- User presses "n" on a permission prompt
- Sandbox prevents a potentially dangerous operation
- Tool call was malformed and rejected by the system

**Failure rate** = Failures / Total tool calls × 100

A failure happens when a tool executes but doesn't succeed. Common scenarios:
- `Edit` tool can't find the text to replace
- `Bash` command returns non-zero exit code
- File operation on non-existent path
- Syntax error in generated code

### Interpreting the Rates

| Rate | Interpretation |
|------|----------------|
| < 1% | Excellent - AI is performing well |
| 1-5% | Normal - expected variation |
| 5-10% | Worth investigating - may indicate issues |
| > 10% | High - consider what's causing failures |

**Note**: Failure rates can legitimately be higher during:
- Exploratory coding (trying different approaches)
- Complex refactoring (more opportunities for errors)
- Unfamiliar codebases (AI making reasonable guesses)

A single session with many retries can skew daily numbers. Use the 7-day view for a more stable picture.

### Model Breakdown

Stats are broken down by model (e.g., `claude-opus-4`, `claude-sonnet-4`) so you can compare performance across different models you've used.

## Additional Context

### IDE Used

Which AI coding tools contributed to your sessions:
- **Claude Code**: Anthropic's CLI tool
- **Codex CLI**: OpenAI's terminal agent
- **Cursor**: AI-powered code editor

If you use multiple tools, all will be listed (e.g., "IDEs Used: Claude Code, Codex CLI"). This helps contextualize stats since different tools may have different error patterns, and is useful for community comparisons.

### Stack Used

Detected tech stack from your project files:
- Python: detected from `pyproject.toml`, `requirements.txt`
- JavaScript/TypeScript: detected from `package.json`
- Rust: detected from `Cargo.toml`
- Go: detected from `go.mod`

This helps contextualize your stats - different stacks may have different error patterns.

### Platform

Your operating system (macOS, Linux, Windows). Useful for understanding platform-specific behaviors.

### Peak Hours

Your three most active hours based on historical session data. Helps identify when you do most of your AI-assisted coding.

## Community Analytics (Optional)

After day 2, you'll see an opt-in prompt for community analytics:

```
┌─ Unlock Community Insights ──────────────────────────────────────────┐
│                                                                      │
│  See how your 0.6% rejection rate compares to:                       │
│    • Other python developers                                         │
│    • Opus vs Sonnet across 1,200+ developers                         │
│    • macOS vs Linux error patterns                                   │
│                                                                      │
│  Share anonymized counts only. No code or content.                   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

If you opt in:
- **What's shared**: Session counts, tool call counts, error rates, detected stack
- **What's NOT shared**: Code, file contents, rule text, project names, any identifying info

See `ap analytics --help` for managing your opt-in status.

## Disabling Daily Stats

Daily stats appear once per day on first command use. They're automatically suppressed for the rest of the day after being shown once.

To check when stats were last shown:
```bash
cat ~/.afterpaths/config.json | jq .last_daily_stats_shown
```
