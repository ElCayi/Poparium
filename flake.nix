{
  description = "Poparium v0.1 · Memoria entre sesiones: libreta personal de acuerdos para tmux";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      src = nixpkgs.lib.fileset.toSource {
        root = ./.;
        fileset = nixpkgs.lib.fileset.unions [ ./Cargo.toml ./Cargo.lock ./src ./assets/popo.json ];
      };
      poparium = pkgs: pkgs.rustPlatform.buildRustPackage {
        pname = "poparium";
        version = "0.1.0";
        inherit src;
        cargoLock.lockFile = ./Cargo.lock;
        # tmux is taken from the user's PATH on purpose: a different tmux
        # version than the running server can't talk to it. Without arguments
        # and outside tmux, the binary opens (or picks up) its own `poparium` session.
        meta.mainProgram = "poparium";
      };
    in
    {
      packages = forAllSystems (pkgs: { default = poparium pkgs; });

      # The tests run as part of the build (cargo test in checkPhase)
      checks = forAllSystems (pkgs: { tests = poparium pkgs; });

      # The toolchain only; the dependencies come from Cargo.lock
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [ cargo rustc clippy rustfmt rust-analyzer ];
        };
      });
    };
}
