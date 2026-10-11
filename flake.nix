{
  description = "popOS v0.1 · Personal Operating System: libreta personal de acuerdos para tmux";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      src = nixpkgs.lib.fileset.toSource {
        root = ./.;
        fileset = nixpkgs.lib.fileset.unions [ ./keepstate.py ./tests ./assets/popo.json ];
      };
    in
    {
      packages = forAllSystems (pkgs: {
        default = pkgs.writeShellApplication {
          name = "popos";
          # tmux is taken from the user's PATH on purpose: a different tmux
          # version than the running server can't talk to it
          text = ''
            py=${pkgs.python3}/bin/python3
            app=${src}/keepstate.py
            # With arguments (--export, --db ...) or already inside tmux: run here.
            # exec -a: the process is called popos, not python3, and that is the
            # name tmux gives its tab
            if [[ $# -gt 0 || -n "''${TMUX:-}" ]] || ! command -v tmux >/dev/null; then
              exec -a popos "$py" "$app" "$@"
            fi
            # Inside the new session TMUX is set, so this same script runs the app
            exec tmux new-session -A -s popos "$0"
          '';
        };
      });

      checks = forAllSystems (pkgs: {
        tests = pkgs.runCommand "popos-tests" { } ''
          cd ${src}
          HOME=$TMPDIR PYTHONDONTWRITEBYTECODE=1 ${pkgs.python3}/bin/python3 -m unittest discover -s tests -v
          touch $out
        '';
      });
    };
}
