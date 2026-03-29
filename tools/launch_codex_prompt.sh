#!/bin/zsh

set -euo pipefail

mode="launch"
prompt=""
prompt_file=""
workspace=""
job_name=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-now)
      mode="run"
      shift
      ;;
    --prompt-file)
      prompt_file="${2:-}"
      shift 2
      ;;
    --prompt)
      prompt="${2:-}"
      shift 2
      ;;
    --workspace)
      workspace="${2:-}"
      shift 2
      ;;
    --job-name)
      job_name="${2:-}"
      shift 2
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$prompt" && -z "$prompt_file" ]]; then
  printf 'missing --prompt or --prompt-file\n' >&2
  exit 1
fi

if [[ -n "$prompt" && -n "$prompt_file" ]]; then
  printf 'use only one of --prompt or --prompt-file\n' >&2
  exit 1
fi

if [[ -z "$workspace" ]]; then
  workspace="$PWD"
fi

script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
workspace_path="$(cd "$workspace" && pwd)"
if [[ -n "$prompt_file" ]]; then
  prompt_path="$(cd "$(dirname "$prompt_file")" && pwd)/$(basename "$prompt_file")"

  if [[ ! -f "$prompt_path" ]]; then
    printf 'prompt file not found: %s\n' "$prompt_path" >&2
    exit 1
  fi
else
  prompt_path=""
fi

if ! command -v codex >/dev/null 2>&1; then
  printf 'codex command not found in PATH\n' >&2
  exit 1
fi

if [[ "$mode" == "run" ]]; then
  cd "$workspace_path"
  if [[ -n "$job_name" ]]; then
    printf 'Launching scheduled Codex job: %s\n' "$job_name"
  fi
  printf 'Workspace: %s\n' "$workspace_path"
  if [[ -n "$prompt_file" ]]; then
    printf 'Prompt file: %s\n\n' "$prompt_path"
    exec codex --no-alt-screen -C "$workspace_path" "$(cat "$prompt_path")"
  fi
  printf 'Prompt: inline\n\n'
  exec codex --no-alt-screen -C "$workspace_path" "$prompt"
fi

if [[ -n "$prompt_file" ]]; then
  terminal_command="$(printf "%q " "$script_path" --run-now --prompt-file "$prompt_path" --workspace "$workspace_path" --job-name "$job_name")"
else
  terminal_command="$(printf "%q " "$script_path" --run-now --prompt "$prompt" --workspace "$workspace_path" --job-name "$job_name")"
fi
terminal_command="${terminal_command% }"
terminal_command="${terminal_command//\\/\\\\}"
terminal_command="${terminal_command//\"/\\\"}"

/usr/bin/osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "$terminal_command"
end tell
APPLESCRIPT
