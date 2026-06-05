# TO DO

## Support for various git worktree structures

We currently use a fixed structure that we expect users to follow: `repo/worktree`, where all the branches are siblings
under `repo/` (E.g. `repo/main`, `repo/feature-new`, etc). 

Implement the changes necessary to support detecting repo structures where this is not the case. For example a
repository where the main branch is not located under `repo/main` and use a different worktree structure in those cases,
such as placing each worktree under the repo root in a dedicated worktree folder: `repo/.worktrees/new-feature`.

Allow configuration of the `.worktrees` folder name.
Allow configuration of the default git worktree structure: sibling folders, sub-folder.

## Claude agents integration

I want to display some information in the session picker to see which sessions have a claude agent running, and some
state (if it is working, needs input, it is finished, etc)

Support listing only the sessions with claude agents

Suggest further integration oportunities.

# IN PROGRESS

# DONE
