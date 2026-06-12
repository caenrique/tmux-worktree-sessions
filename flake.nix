{
  description = "tmux-worktree-sessions dev environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.git
            pkgs.tmux
            pkgs.fzf
            pkgs.fd
            pkgs.shellcheck
            pkgs.vhs
            pkgs.python3
            pkgs.uv
          ];

          shellHook = ''
            uv sync --quiet
          '';
        };
      });
    };
}
