# VHS tape file for afterpaths demo
# Run with: vhs demo.tape

Output demo.gif

Set FontSize 13
Set Width 1000
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

# Start with audit overview
Type "ap audit"
Enter
Sleep 3s

Enter
Sleep 300ms

# Show raw session transcript
Type "ap show 5 --raw --limit 12"
Enter
Sleep 3s

Enter
Sleep 300ms

# Show the summary
Type "ap show 5"
Enter
Sleep 5s

Enter
Sleep 300ms

# Show the generated rules (already extracted from summaries)
Type "head -20 .claude/rules/gotchas.md"
Enter
Sleep 6s
