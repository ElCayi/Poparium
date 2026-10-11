#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  py="python3"
else
  # NixOS sin python3 en el PATH: lo trae nix al vuelo
  py="nix shell nixpkgs#python3 -c python3"
fi
if [[ -n "${TMUX:-}" && $py == python3 ]]; then
  exec -a popos python3 -m popos  # tmux names the tab after the process: popos
elif [[ -n "${TMUX:-}" ]]; then
  exec $py -m popos
elif command -v tmux >/dev/null 2>&1; then
  exec tmux new-session -A -s popos -c "$PWD" "$PWD/run.sh"
else
  exec $py -m popos
fi
