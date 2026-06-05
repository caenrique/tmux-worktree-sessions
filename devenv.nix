{ pkgs, lib, config, inputs, ... }:

{
  # System tools needed to run the test suite end-to-end. tmux/fzf/fd
  # are runtime deps of the plugin; bats/shellcheck drive the shell-side
  # checks; git is needed by the pytest fixtures (real repos under tmp).
  packages = [
    pkgs.git
    pkgs.tmux
    pkgs.fzf
    pkgs.fd
    pkgs.bats
    pkgs.shellcheck
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
  # the project venv. System tools (bats, shellcheck) come from
  # `packages` above and are on PATH unconditionally.
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
    "python:typecheck" = {
      exec = "uv run mypy scripts/tmux_sessions";
      before = [ "devenv:enterTest" ];
    };
    "bats:test" = {
      exec = "bats --print-output-on-failure tests/";
      before = [ "devenv:enterTest" ];
    };
    "shellcheck:lint" = {
      exec = ''
        shellcheck --severity=warning -x \
          scripts/*.sh tmux-sessions.tmux \
          tests/test_helper.bash tests/helpers/*.bash \
          tests/fixtures/bin/*
      '';
      before = [ "devenv:enterTest" ];
    };
  };

  enterTest = ''
    echo "All checks passed"
  '';

  # See full reference at https://devenv.sh/reference/options/
}
