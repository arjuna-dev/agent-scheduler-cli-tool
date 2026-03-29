#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


SUPPORT_DIR = Path.home() / ".local" / "share" / "agent-scheduler"
RUNS_DIR = SUPPORT_DIR / "runs"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
DOMAIN = f"gui/{os.getuid()}"
LAUNCHCTL = "/bin/launchctl"


def sanitize_name(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9.-]+", "-", name.strip().lower()).strip("-.")
    if not value:
        raise SystemExit("job name must contain at least one alphanumeric character")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled agent jobs with local runtime markers.")
    sub = parser.add_subparsers(dest="mode", required=True)

    recurring = sub.add_parser("recurring", help="Run a recurring job with local trigger state")
    recurring.add_argument("--job", required=True, help="Logical job name")
    recurring.add_argument("--trigger-kind", required=True, choices=("scheduled", "recovery", "manual"))
    recurring.add_argument("--scheduled-time", required=True, help="Target time in HH:MM")
    recurring.add_argument("--day", type=int, help="Allowed day of month")
    recurring.add_argument("--month", type=int, help="Allowed month")
    recurring.add_argument("--command", required=True, help="Absolute path to the script or file to run")
    recurring.add_argument("--open", action="store_true", help="Run the command through /usr/bin/open")
    recurring.add_argument(
        "--weekday",
        action="append",
        type=int,
        default=[],
        help="Allowed ISO weekday (1=Monday ... 7=Sunday). Repeat for multiple days.",
    )

    once = sub.add_parser("once", help="Run a one-time job with a local trace record")
    once.add_argument("--job", required=True, help="Logical one-off job name")
    once.add_argument("--cleanup-label", help="Exact launchd label to remove after the job fires")
    once.add_argument("--command", required=True, help="Absolute path to the script or file to run")
    once.add_argument("--open", action="store_true", help="Run the command through /usr/bin/open")
    parser_argv, command_args = split_command_args(sys.argv[1:])
    args = parser.parse_args(parser_argv)
    args.command_args = command_args
    return args


def parse_daily_time(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise SystemExit(f"invalid time '{value}'. expected HH:MM") from exc
    return parsed.hour, parsed.minute


def split_command_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    idx = argv.index("--")
    return argv[:idx], argv[idx + 1 :]


def command_argv(command: str, command_args: list[str], use_open: bool) -> list[str]:
    command_path = os.path.expanduser(command)
    if use_open:
        return ["/usr/bin/open", command_path, *command_args]
    return [command_path, *command_args]


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_run_markdown(path: Path, lines: list[str]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def recurring_run_dir(job: str, now: datetime, slot: str) -> Path:
    return RUNS_DIR / "recurring" / sanitize_name(job) / now.strftime("%Y-%m-%d") / slot


def once_run_dir(job: str, now: datetime) -> Path:
    return RUNS_DIR / "once" / sanitize_name(job) / now.strftime("%Y-%m-%d-%H%M%S")


def should_skip_recovery(now: datetime, scheduled_hour: int, scheduled_minute: int) -> bool:
    return (now.hour * 60 + now.minute) < (scheduled_hour * 60 + scheduled_minute)


def slot_key(scheduled_time: str) -> str:
    hour, minute = parse_daily_time(scheduled_time)
    return f"{hour:02d}{minute:02d}"


def should_skip_weekday(now: datetime, weekdays: list[int]) -> bool:
    return bool(weekdays) and now.isoweekday() not in weekdays


def should_skip_calendar_day(now: datetime, day: int | None, month: int | None) -> bool:
    if month is not None and now.month != month:
        return True
    if day is not None and now.day != day:
        return True
    return False


def acquire_lock(lock_dir: Path) -> bool:
    try:
        lock_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        return False
    return True


def run_command(argv: list[str], extra_env: dict[str, str]) -> int:
    env = os.environ.copy()
    env.update(extra_env)
    try:
        proc = subprocess.run(argv, env=env, check=False)
    except FileNotFoundError:
        return 127
    return proc.returncode


def cleanup_once_job(label: str | None) -> dict[str, object]:
    if not label:
        return {"attempted": False, "reason": "missing label"}
    plist_path = LAUNCH_AGENTS_DIR / f"{label}.plist"
    info: dict[str, object] = {
        "attempted": True,
        "label": label,
        "plist": str(plist_path),
        "plist_exists_before": plist_path.exists(),
    }
    try:
        plist_path.unlink(missing_ok=True)
        info["unlink_error"] = None
    except OSError as exc:
        info["unlink_error"] = str(exc)
    info["plist_exists_after_unlink"] = plist_path.exists()
    cleanup_script = (
        f'sleep 1; "{LAUNCHCTL}" bootout "{DOMAIN}" "{plist_path}" >/dev/null 2>&1 || true; '
        f'"{LAUNCHCTL}" disable "{DOMAIN}/{label}" >/dev/null 2>&1 || true'
    )
    proc = subprocess.Popen(
        ["/bin/sh", "-c", cleanup_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    info["deferred_cleanup_pid"] = proc.pid
    return info


def runtime_env(*, job: str, trigger_kind: str, run_dir: Path, scheduled_time: str | None = None) -> dict[str, str]:
    env = {
        "AGENT_SCHEDULER_JOB": job,
        "AGENT_SCHEDULER_TRIGGER_KIND": trigger_kind,
        "AGENT_SCHEDULER_RUN_DIR": str(run_dir),
        "HEYDATA_SCHEDULE_JOB": job,
        "HEYDATA_TRIGGER_KIND": trigger_kind,
        "HEYDATA_RUN_DIR": str(run_dir),
    }
    if scheduled_time is not None:
        env["AGENT_SCHEDULER_SCHEDULED_TIME"] = scheduled_time
        env["HEYDATA_SCHEDULED_TIME"] = scheduled_time
    return env


def handle_recurring(args: argparse.Namespace) -> int:
    now = datetime.now().astimezone()
    if should_skip_weekday(now, args.weekday):
        return 0
    if should_skip_calendar_day(now, args.day, args.month):
        return 0

    scheduled_hour, scheduled_minute = parse_daily_time(args.scheduled_time)
    run_slot = slot_key(args.scheduled_time)
    if args.trigger_kind == "recovery" and should_skip_recovery(now, scheduled_hour, scheduled_minute):
        return 0

    run_dir = recurring_run_dir(args.job, now, run_slot)
    run_dir.mkdir(parents=True, exist_ok=True)

    marker_path = run_dir / "trigger.json"
    if marker_path.exists():
        return 0

    lock_dir = run_dir / ".trigger-lock"
    if not acquire_lock(lock_dir):
        return 0

    try:
        if marker_path.exists():
            return 0

        fired_at = datetime.now().astimezone()
        command = command_argv(args.command, args.command_args, args.open)
        marker_payload = {
            "job": sanitize_name(args.job),
            "trigger_kind": args.trigger_kind,
            "scheduled_time": args.scheduled_time,
            "slot_key": run_slot,
            "fired_at": fired_at.isoformat(timespec="seconds"),
            "pid": os.getpid(),
            "command": command,
        }
        write_json(marker_path, marker_payload)

        run_md = run_dir / "run.md"
        run_md.write_text(
            "\n".join(
                [
                    f"# {sanitize_name(args.job)} Run",
                    "",
                    f"- Date: {fired_at.strftime('%Y-%m-%d')}",
                    f"- Trigger kind: {args.trigger_kind}",
                    f"- Fired at: {fired_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                    f"- Scheduled time: {args.scheduled_time}",
                    f"- Slot key: {run_slot}",
                    f"- Command: {' '.join(command)}",
                    "",
                    "## Result",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        exit_code = run_command(
            command,
            runtime_env(
                job=sanitize_name(args.job),
                trigger_kind=args.trigger_kind,
                run_dir=run_dir,
                scheduled_time=args.scheduled_time,
            ),
        )
        finished_at = datetime.now().astimezone()
        append_run_markdown(
            run_md,
            [
                f"- Exit code: {exit_code}",
                f"- Finished at: {finished_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            ],
        )
        return exit_code
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def handle_once(args: argparse.Namespace) -> int:
    now = datetime.now().astimezone()
    run_dir = once_run_dir(args.job, now)
    run_dir.mkdir(parents=True, exist_ok=True)

    command = command_argv(args.command, args.command_args, args.open)
    run_md = run_dir / "run.md"
    run_md.write_text(
        "\n".join(
            [
                f"# {sanitize_name(args.job)} One-Off Run",
                "",
                f"- Fired at: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                f"- Command: {' '.join(command)}",
                "",
                "## Result",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cleanup_info: dict[str, object] | None = None
    try:
        exit_code = run_command(
            command,
            runtime_env(
                job=sanitize_name(args.job),
                trigger_kind="one-off",
                run_dir=run_dir,
            ),
        )
        finished_at = datetime.now().astimezone()
        append_run_markdown(
            run_md,
            [
                f"- Exit code: {exit_code}",
                f"- Finished at: {finished_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            ],
        )
        return exit_code
    finally:
        cleanup_info = cleanup_once_job(args.cleanup_label)
        append_run_markdown(
            run_md,
            [
                "",
                "## Cleanup",
                f"- Attempted: {cleanup_info.get('attempted')}",
                f"- Label: {cleanup_info.get('label', '')}",
                f"- Plist: {cleanup_info.get('plist', '')}",
                f"- Plist existed before: {cleanup_info.get('plist_exists_before')}",
                f"- unlink error: {cleanup_info.get('unlink_error', '')}",
                f"- Plist exists after unlink: {cleanup_info.get('plist_exists_after_unlink')}",
                f"- Deferred cleanup pid: {cleanup_info.get('deferred_cleanup_pid', '')}",
            ],
        )


def main() -> None:
    args = parse_args()
    if args.mode == "recurring":
        raise SystemExit(handle_recurring(args))
    raise SystemExit(handle_once(args))


if __name__ == "__main__":
    main()
