# Agent Scheduler

`agent-scheduler` is a macOS `launchd` wrapper for agent-driven scheduling.

The public CLI intentionally exposes only two schedule types:

- `schedule-codex`
- `schedule-notification`

There is no generic `schedule` command anymore. That is deliberate so agents do not choose an arbitrary-command path when the real intent is a Codex run or a notification.

## Install

```sh
./tools/install-global-scheduler.sh
```

That installs a global `agent-scheduler` symlink into the first writable directory among:

- `/opt/homebrew/bin`
- `~/.local/bin`
- `~/bin`

Verify:

```sh
agent-scheduler -h
```

## Commands

Lifecycle:

```sh
agent-scheduler list
agent-scheduler get-time <job>
agent-scheduler status <job>
agent-scheduler enable <job>
agent-scheduler disable <job>
agent-scheduler restart <job>
agent-scheduler run <job>
agent-scheduler get-prompt <job>
agent-scheduler edit <job> --daily 10:00 --prompt "Updated prompt"
agent-scheduler remove <job>
agent-scheduler remove <exact-label> --label
agent-scheduler prune-once
agent-scheduler remove-all
```

Agent-facing scheduling:

```sh
agent-scheduler schedule-codex morning-review --daily 09:30 --prompt "Review the repo and summarize blockers." --workspace /tmp/repo
agent-scheduler schedule-notification drink-water --daily 14:00 --title "Reminder" --body "Drink water."
```

One-off examples:

```sh
agent-scheduler schedule-codex release-check --at "2026-04-01 14:30" --prompt "Check release readiness and report risks." --workspace /tmp/repo
agent-scheduler schedule-notification deploy-window --at "2026-04-01 14:30" --title "Deploy" --body "Deploy window opens now."
```

## Behavior

- Recurring jobs install a primary `launchd` job plus a recovery job by default.
- Recovery jobs wake every 30 minutes after the scheduled time and exit if that slot already fired.
- One-off jobs remove themselves after they run.
- `prune-once` removes stale one-off plist leftovers for one-off jobs that are no longer loaded in `launchd`.
- `remove-all` removes every scheduler-managed job, including recurring, recovery, and one-off jobs.
- `schedule-codex` stores the effective prompt text directly in the scheduled job.
- Every Codex schedule prepends hardcoded instructions to treat the working directory as the workspace root, read `AGENTS.md` there first when it exists, pay attention to relevant workspace files, and save the full session as markdown under `WORKSPACE/SESSIONS/` with a timestamped filename.
- Recurring Codex schedules also prepend hardcoded instructions to inspect the most recent prior session date and create a distilled day-level memory file under `WORKSPACE/MEMORY/YYYY-MM-DD.md` when that memory does not already exist.
- `get-prompt` reads the stored prompt from the installed job plist.
- `edit` updates an existing schedule in place while preserving unspecified fields.
- Runtime logs and markers are stored under `~/.local/share/agent-scheduler`.

Runtime environment variables exposed to scheduled commands:

- `AGENT_SCHEDULER_JOB`
- `AGENT_SCHEDULER_TRIGGER_KIND`
- `AGENT_SCHEDULER_RUN_DIR`
- `AGENT_SCHEDULER_PROMPT` for Codex schedules
- `AGENT_SCHEDULER_SCHEDULED_TIME` for recurring runs
- `HEYDATA_SCHEDULE_JOB`
- `HEYDATA_TRIGGER_KIND`
- `HEYDATA_RUN_DIR`
- `HEYDATA_SCHEDULED_TIME` for recurring runs

Useful flags shared by both schedule types:

- `--daily`, `--weekdays`, `--weekly`, `--at`
- explicit calendar fields: `--hour`, `--minute`, `--day`, `--month`, `--weekday`
- `--once` and `--year` for explicit one-off schedules
- `--cwd`
- `--stdout`
- `--stderr`
- `--env KEY=VALUE`
- `--no-recurring-fallback`

## Files

- [tools/scheduler.py](/Users/alejandrocamus/Documents/dev/agent-scheduler/tools/scheduler.py): CLI entrypoint and plist generation
- [tools/job_runner.py](/Users/alejandrocamus/Documents/dev/agent-scheduler/tools/job_runner.py): runtime guard, run logging, and one-off cleanup
- [tools/launch_codex_prompt.sh](/Users/alejandrocamus/Documents/dev/agent-scheduler/tools/launch_codex_prompt.sh): Codex launcher used by `schedule-codex`
- [tools/install-global-scheduler.sh](/Users/alejandrocamus/Documents/dev/agent-scheduler/tools/install-global-scheduler.sh): global installer

## Testing

```sh
python3 -m unittest discover -s tests -v
```
