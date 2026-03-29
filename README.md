# Agent Scheduler

`agent-scheduler` is a small macOS `launchd` wrapper for scheduling local commands. It is designed for agent workflows, not interactive human use.

The CLI installs and removes `LaunchAgents`, supports recurring and one-off schedules, and records each execution under `~/.local/share/agent-scheduler/runs`.

The agent-facing entrypoints are explicit:

- `schedule-codex` for Codex runs
- `schedule-notification` for macOS notifications
- `schedule` and `schedule-once` remain available as low-level generic command schedulers

## Install

Global install is a symlink created by [tools/install-global-scheduler.sh](/Users/alejandrocamus/Documents/dev/declawtter-w-scheduler/tools/install-global-scheduler.sh):

```sh
./tools/install-global-scheduler.sh
```

That installs `agent-scheduler` into the first writable directory of:

- `/opt/homebrew/bin`
- `~/.local/bin`
- `~/bin`

## Behavior

- Recurring jobs install a primary `launchd` job plus a recovery job by default.
- One-off jobs remove themselves after they fire.
- Command paths are normalized to absolute paths at install time.
- Extra command arguments are passed after `--`.
- Runtime markers and run logs are written under `~/.local/share/agent-scheduler`.

Runtime environment variables exposed to scheduled commands:

- `AGENT_SCHEDULER_JOB`
- `AGENT_SCHEDULER_TRIGGER_KIND`
- `AGENT_SCHEDULER_RUN_DIR`
- `AGENT_SCHEDULER_SCHEDULED_TIME` for recurring runs
- `HEYDATA_SCHEDULE_JOB`
- `HEYDATA_TRIGGER_KIND`
- `HEYDATA_RUN_DIR`
- `HEYDATA_SCHEDULED_TIME` for recurring runs

## Commands

This CLI is intended to be machine-invoked. Labels are deterministic:

- Recurring primary: `com.agent-scheduler.recurring.<name>`
- Recurring recovery: `com.agent-scheduler.recurring.<name>.recovery`
- One-off: `com.agent-scheduler.once.<name>`

Inspection and lifecycle:

```sh
agent-scheduler list
agent-scheduler status <job-or-label>
agent-scheduler enable <job-or-label>
agent-scheduler disable <job-or-label>
agent-scheduler restart <job-or-label>
agent-scheduler run <job-name>
agent-scheduler remove <job-or-label>
agent-scheduler remove <exact-label> --label
```

## Scheduling

Main agent-oriented commands:

```sh
agent-scheduler schedule-codex morning-review --daily 09:30 --prompt "Review the repo and summarize blockers." --workspace /tmp/repo
agent-scheduler schedule-notification drink-water --daily 14:00 --title "Reminder" --body "Drink water."
```

Codex one-off example:

```sh
agent-scheduler schedule-codex release-check --at "2026-04-01 14:30" --prompt "Check release readiness and report risks." --workspace /tmp/repo
```

Notification one-off example:

```sh
agent-scheduler schedule-notification deploy-window --at "2026-04-01 14:30" --title "Deploy" --body "Deploy window opens now."
```

Recurring examples:

```sh
agent-scheduler schedule repo-sync --daily 09:30 --command ./tools/sync.sh
agent-scheduler schedule weekday-report --weekdays 18:00 --command ./tools/report.sh
agent-scheduler schedule monday-review --weekly mon@10:15 --command ./tools/review.sh
agent-scheduler schedule month-end --hour 9 --minute 0 --day 1 --command ./tools/close.sh
```

One-off examples:

```sh
agent-scheduler schedule-once ad-hoc-task --at "2026-04-01 14:30" --command ./tools/task.sh
agent-scheduler schedule deploy-window --at "2026-04-01 14:30" --command ./tools/task.sh
agent-scheduler schedule maintenance --once --year 2026 --month 4 --day 1 --hour 14 --minute 30 --command ./tools/task.sh
```

Low-level generic command example:

```sh
agent-scheduler schedule prompt-job --daily 08:00 --command ./tools/launch_codex_prompt.sh -- --prompt-file /tmp/prompt.md
```

`schedule-codex` stores the prompt text directly in the scheduled job. It does not require a prompt file at runtime.

Useful flags:

- `--cwd` sets `WorkingDirectory`
- `--stdout` sets `StandardOutPath`
- `--stderr` sets `StandardErrorPath`
- `--env KEY=VALUE` adds environment variables to the `launchd` job
- `--open` runs the target through `/usr/bin/open`
- `--no-recurring-fallback` disables the paired recovery job for recurring schedules

## Files

- [tools/scheduler.py](/Users/alejandrocamus/Documents/dev/declawtter-w-scheduler/tools/scheduler.py): CLI entrypoint and `launchd` plist generator
- [tools/job_runner.py](/Users/alejandrocamus/Documents/dev/declawtter-w-scheduler/tools/job_runner.py): runtime guard, run logging, and one-off cleanup
- [tools/install-global-scheduler.sh](/Users/alejandrocamus/Documents/dev/declawtter-w-scheduler/tools/install-global-scheduler.sh): global symlink installer
- `~/Library/LaunchAgents`: installed plists
- `~/.local/share/agent-scheduler/jobs`: generated wrapper scripts
- `~/.local/share/agent-scheduler/runs`: per-run logs and markers

## Testing

```sh
python3 -m unittest discover -s tests -v
```
