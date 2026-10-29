{
  description = "popOS v0.1 · Personal Operating System: libreta personal de acuerdos para tmux";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      src = nixpkgs.lib.fileset.toSource {
        root = ./.;
        fileset = nixpkgs.lib.fileset.unions [ ./Cargo.toml ./Cargo.lock ./src ./assets/popo.json ];
      };
      popos = pkgs: pkgs.rustPlatform.buildRustPackage {
        pname = "popos";
        version = "0.1.0";
        inherit src;
        cargoLock.lockFile = ./Cargo.lock;
        # tmux is taken from the user's PATH on purpose: a different tmux
        # version than the running server can't talk to it. Without arguments
        # and outside tmux, the binary opens (or picks up) its own `popos` session.
        meta.mainProgram = "popos";
      };
    in
    {
      packages = forAllSystems (pkgs: { default = popos pkgs; });

      # The tests run as part of the build (cargo test in checkPhase)
      checks = forAllSystems (pkgs: { tests = popos pkgs; });

      # The toolchain only; the dependencies come from Cargo.lock
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [ cargo rustc clippy rustfmt rust-analyzer ];
        };
      });
    };
}
