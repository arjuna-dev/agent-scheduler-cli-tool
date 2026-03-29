#!/bin/zsh

set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
source_path="$project_dir/tools/scheduler.py"
target_name="agent-scheduler"

choose_bin_dir() {
  local candidate
  for candidate in /opt/homebrew/bin "$HOME/.local/bin" "$HOME/bin"; do
    if [[ -d "$candidate" && -w "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf 'no writable bin directory found in /opt/homebrew/bin, ~/.local/bin, or ~/bin\n' >&2
  exit 1
}

bin_dir="$(choose_bin_dir)"
target_path="$bin_dir/$target_name"

chmod +x "$source_path"
ln -sf "$source_path" "$target_path"

printf 'Installed %s -> %s\n' "$target_path" "$source_path"
printf 'Run `%s -h` to verify.\n' "$target_name"
