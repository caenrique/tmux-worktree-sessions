# README demo: trigger the picker, pick a project, open the branch picker,
# create a new branch worktree, land in a fresh tmux session.
#
# Render with:    bash demo/setup.sh && vhs demo/readme.tape
# Output GIF:     /tmp/tws-demo/readme.gif (NOT committed; upload separately)

Output "/tmp/tws-demo/readme.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 70ms
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
Sleep 800ms

# Open the session picker (default trigger remapped to Ctrl-G for the demo).
Ctrl+G
Sleep 1500ms

# Filter to webapp project.
Type "webapp"
Sleep 1s

# Open the branch picker for webapp instead of just opening it.
Ctrl+W
Sleep 1500ms

# [new] is selected by default — Enter opens the new-branch-name prompt.
Enter
Sleep 1s

# Type the new branch name and create the worktree.
Type "feature/demo-readme"
Sleep 1s
Enter

# Wait for the new tmux session to switch in, then prove the worktree
# is real: print pwd + branch.
Sleep 1500ms
Type "pwd && git branch --show-current"
Sleep 400ms
Enter

# Hold on the resulting frame.
Sleep 3s
