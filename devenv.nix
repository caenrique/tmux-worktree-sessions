{ pkgs, lib, config, inputs, ... }:

{
  # System tools needed to run the test suite end-to-end. tmux/fzf/fd
  # are runtime deps of the plugin; shellcheck drives the one remaining
  # shell file (the TPM entry point); git is needed by the pytest
  # fixtures (real repos under tmp).
  packages = [
    pkgs.git
    pkgs.tmux
    pkgs.fzf
    pkgs.fd
    pkgs.shellcheck
    pkgs.vhs
  ];

  # uv-driven Python dev environment. `sync.enable` runs `uv sync` on
  # shell entry, which installs the default dependency group (`dev` per
  # PEP 735) into a project-local venv and puts ruff/mypy/pytest on PATH.
  languages.python = {
    enable = true;
    venv.enable = true;
    uv = {
      enable = true;
      sync.enable = true;
    };
  };

  # Each task is individually runnable (`devenv tasks run python:test`)
  # and also wired before `devenv:enterTest` so `devenv test` triggers
  # the whole suite. The uv venv is auto-activated only inside the
  # interactive `devenv shell`, not in task execution contexts, so the
  # Python tasks shell out via `uv run` to pick up pytest/ruff/mypy from
  # the project venv. System tools (shellcheck) come from `packages`
  # above and are on PATH unconditionally.
  tasks = {
    "python:test" = {
      exec = "uv run pytest tests/python";
      before = [ "devenv:enterTest" ];
    };
    "python:lint" = {
      exec = "uv run ruff check scripts/ tests/python";
      before = [ "devenv:enterTest" ];
    };
    "python:format-check" = {
      exec = "uv run ruff format --check scripts/ tests/python";
      before = [ "devenv:enterTest" ];
    };
    "python:format" = {
      exec = "uv run ruff format scripts/ tests/python";
    };
    "python:typecheck" = {
      exec = "uv run mypy scripts/tmux_worktree_sessions";
      before = [ "devenv:enterTest" ];
    };
    "shellcheck:lint" = {
      exec = "shellcheck --severity=warning tmux-worktree-sessions.tmux";
      before = [ "devenv:enterTest" ];
    };
    "demo:render" = {
      exec = "bash demo/setup.sh && vhs demo/readme.tape";
    };
    # Publish the rendered GIF to the `demo-assets` GitHub release the
    # README links to. By default `demo:render` runs first via the
    # `after` dependency; pass `--mode single` to publish whatever is
    # already at /tmp/tws-demo/readme.gif without re-rendering.
    # Requires `gh` to be authenticated against github.com.
    "demo:release" = {
      exec = "bash demo/publish.sh";
      after = [ "demo:render" ];
    };
  };

  enterTest = ''
    echo "All checks passed"
  '';

  # See full reference at https://devenv.sh/reference/options/
}
