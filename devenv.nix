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
  # the whole suite. Tools are invoked by bare name — the uv venv and
  # the system packages above are already on PATH inside the dev shell.
  tasks = {
    "python:test" = {
      exec = "pytest tests/python";
      before = [ "devenv:enterTest" ];
    };
    "python:lint" = {
      exec = "ruff check scripts/ tests/python";
      before = [ "devenv:enterTest" ];
    };
    "python:format-check" = {
      exec = "ruff format --check scripts/ tests/python";
      before = [ "devenv:enterTest" ];
    };
    "python:typecheck" = {
      exec = "mypy scripts/tmux_sessions";
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
