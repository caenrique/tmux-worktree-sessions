# README demo: trigger the picker, pick a project, open the branch picker,
# create a new branch worktree, land in a fresh tmux session.
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
Sleep 1500ms

# Show the entry-point keybinding so viewers know what's about to happen.
# (In real use the default is Ctrl+Shift+S; demo/tmux.conf rebinds to
# Ctrl+G because VHS 0.11 has no Shift+ modifier.)
# Hide the typing of the printf, but keep its output on screen — that
# way the banner appears as if it were always there. See SKILL.md for
# the pattern.
Hide
Type `clear; printf '\n  \033[1;33m▶\033[0m  Press \033[1;36;7m Ctrl+G \033[0m to open the session picker\n\n'`
Enter
Sleep 200ms
Show
Sleep 3500ms

# Open the session picker.
Ctrl+G
Sleep 3s

# Filter to webapp project (the picker shows its own keymap hints in the
# header above the filter, including ctrl-w:worktree).
Type "webapp"
Sleep 2500ms

# Ctrl+W from the session picker opens the branch picker for the
# selected project instead of just attaching to it.
Ctrl+W
Sleep 3s

# [new branch] is selected by default — Enter opens the new-branch-name
# prompt. The header shows enter:checkout / ctrl-bs:back / ctrl-f:refresh.
Enter
Sleep 2s

# Type the branch name and create the worktree. The plugin creates a
# new git worktree as a sibling directory and starts a tmux session in it.
Type "feature/demo-readme"
Sleep 1500ms
Enter

# Wait for the new tmux session to switch in (status-left should now
# show the new session's display name), then prove the worktree is
# real: print pwd + branch.
Sleep 2500ms
Type "pwd && git branch --show-current"
Sleep 600ms
Enter

# Hold on the resulting frame.
Sleep 4s
