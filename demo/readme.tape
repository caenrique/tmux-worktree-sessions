# README demo: trigger the picker, pick a project, open the branch picker,
# create a new branch worktree, land in a fresh tmux session, then switch back.
#
# Render with:    bash demo/setup.sh && vhs demo/readme.tape
# Output GIF:     /tmp/tws-demo/readme.gif (NOT committed; upload separately)

Output "/tmp/tws-demo/readme.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 720
Set Theme "Catppuccin Mocha"
Set TypingSpeed 100ms
Set Padding 30
Set WindowBar "Colorful"

# Point HOME at a clean dir so bash loads only the minimal .bashrc that
# demo/setup.sh writes there (instead of the user's .bashrc → .zshenv →
# vendor profile.sh chain). Env directives must come AFTER all Set
# directives — VHS ignores any Set seen after the first non-Set command.
Env HOME "/tmp/tws-demo/home"

# --- setup: launch tmux quietly with the demo config ---
Hide
Type "tmux -L tws-demo kill-server 2>/dev/null; cd /tmp/tws-demo/Projects && clear"
Enter
Sleep 300ms
Type "tmux -L tws-demo -f /tmp/tws-demo/repo/demo/tmux.conf new-session -s demo"
Enter
Sleep 1500ms
Show

# --- demo body ---
Sleep 2500ms

Ctrl+G
Sleep 3s

# Filter to webapp project. The picker's own header (above the prompt)
# shows the in-picker bindings, including `ctrl-w:worktree`.
Type "webapp"
Sleep 2500ms

# Ctrl+W opens the branch picker for the selected project.
Ctrl+W
Sleep 3s

# `[new branch]` is selected by default — Enter opens the name prompt.
Enter
Sleep 2s

# Branch name deliberately does NOT contain "demo": the next step
# searches the running-sessions list for `demo` to switch back, and a
# substring overlap would let fzf rank the just-created (currently
# attached) session above the target.
Type "feature/checkout"
Sleep 1500ms
Enter

# We land in the new tmux session (status-left flips to the new name).
# Prove the worktree is real: print pwd + branch.
Sleep 2500ms
Type "pwd && git branch --show-current"
Sleep 600ms
Enter
Sleep 3500ms

# --- switch back to the original demo session ---
Sleep 1500ms

Ctrl+G
Sleep 2500ms

# The previous session (`demo`) is pinned near the top of the running
# list; type to narrow, Enter to attach.
Type "demo"
Sleep 1500ms
Enter

Sleep 3s
