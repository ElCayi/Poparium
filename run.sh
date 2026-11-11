#!/usr/bin/env bash
# Poparium from the project folder, built if needed. Outside tmux the binary opens
# (or picks up) its own `poparium` session; inside, it opens in the current pane.
set -euo pipefail
cd "$(dirname "$0")"
if command -v cargo >/dev/null 2>&1; then
  cargo build --release --locked --quiet
else
  # NixOS sin cargo en el PATH: lo trae nix al vuelo
  nix shell nixpkgs#cargo nixpkgs#rustc nixpkgs#gcc -c cargo build --release --locked --quiet
fi
exec target/release/poparium "$@"
