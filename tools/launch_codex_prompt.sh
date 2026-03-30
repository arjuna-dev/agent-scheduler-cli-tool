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

script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
if [[ -n "$workspace" ]]; then
  workspace_path="$(cd "$workspace" && pwd)"
else
  workspace_path=""
fi
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
  if [[ -n "$workspace_path" ]]; then
    cd "$workspace_path"
  fi
  if [[ -n "$job_name" ]]; then
    printf 'Launching scheduled Codex job: %s\n' "$job_name"
  fi
  if [[ -n "$workspace_path" ]]; then
    printf 'Workspace: %s\n' "$workspace_path"
  else
    printf 'Workspace: none\n'
  fi
  if [[ -n "$prompt_file" ]]; then
    prompt_contents="$(cat "$prompt_path")"
    case "$prompt_path" in
      "${TMPDIR:-/tmp}"/agent-scheduler-prompt.*.txt)
        rm -f "$prompt_path"
        ;;
    esac
    printf 'Prompt file: %s\n\n' "$prompt_path"
    if [[ -n "$workspace_path" ]]; then
      exec codex --no-alt-screen -C "$workspace_path" "$prompt_contents"
    fi
    exec codex --no-alt-screen "$prompt_contents"
  fi
  printf 'Prompt: inline\n\n'
  if [[ -n "$workspace_path" ]]; then
    exec codex --no-alt-screen -C "$workspace_path" "$prompt"
  fi
  exec codex --no-alt-screen "$prompt"
fi

if [[ -z "$prompt_file" ]]; then
  staged_prompt_file="$(mktemp "${TMPDIR:-/tmp}/agent-scheduler-prompt.XXXXXX.txt")"
  printf '%s' "$prompt" > "$staged_prompt_file"
  prompt_path="$staged_prompt_file"
fi
terminal_command_parts=("$script_path" --run-now --prompt-file "$prompt_path" --job-name "$job_name")
if [[ -n "$workspace_path" ]]; then
  terminal_command_parts+=(--workspace "$workspace_path")
fi
terminal_command="$(printf "%q " "${terminal_command_parts[@]}")"
terminal_command="${terminal_command% }"
terminal_command="${terminal_command//\"/\\\"}"

/usr/bin/osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "$terminal_command"
end tell
APPLESCRIPT
