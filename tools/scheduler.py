#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from datetime import datetime
from calendar import monthrange
from pathlib import Path
import re


PROJECT_DIR = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
SUPPORT_DIR = Path.home() / ".local" / "share" / "agent-scheduler"
GENERATED_JOBS_DIR = SUPPORT_DIR / "jobs"
DEFAULT_PATH = os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
DOMAIN = f"gui/{os.getuid()}"
LABEL_PREFIX = "com.agent-scheduler"
ISO_WEEKDAY_NAMES = {
    "mon": 1,
    "monday": 1,
    "tue": 2,
    "tues": 2,
    "tuesday": 2,
    "wed": 3,
    "wednesday": 3,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "thursday": 4,
    "fri": 5,
    "friday": 5,
    "sat": 6,
    "saturday": 6,
    "sun": 7,
    "sunday": 7,
}


def sanitize_name(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9.-]+", "-", name.strip().lower()).strip("-.")
    if not value:
        raise SystemExit("name must contain at least one alphanumeric character")
    return value


def print_text(text: str) -> None:
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def ensure_dirs() -> None:
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_JOBS_DIR.mkdir(parents=True, exist_ok=True)


def build_standard_env(extra_env: list[str]) -> dict[str, str]:
    env = {"HOME": str(Path.home()), "PATH": DEFAULT_PATH}
    for item in extra_env:
        if "=" not in item:
            raise SystemExit(f"invalid env entry '{item}'. expected KEY=VALUE")
        key, value = item.split("=", 1)
        env[key] = value
    return env


def installed_plist_path(label: str) -> Path:
    return LAUNCH_AGENTS_DIR / f"{label}.plist"


def plist_exists(label: str) -> bool:
    return installed_plist_path(label).exists()


def write_plist(path: Path, payload: dict) -> None:
    with path.open("wb") as fh:
        plistlib.dump(payload, fh, sort_keys=False)


def bootout(label: str) -> None:
    run_launchctl("bootout", DOMAIN, str(installed_plist_path(label)), check=False)


def bootstrap(label: str) -> None:
    run_launchctl("bootstrap", DOMAIN, str(installed_plist_path(label)))


def enable(label: str) -> None:
    run_launchctl("enable", f"{DOMAIN}/{label}")


def disable(label: str) -> None:
    run_launchctl("disable", f"{DOMAIN}/{label}")


def kickstart(label: str) -> None:
    run_launchctl("kickstart", "-k", f"{DOMAIN}/{label}")


def launchctl_print(label: str) -> subprocess.CompletedProcess[str]:
    return run_launchctl("print", f"{DOMAIN}/{label}", check=False)


def install_job(label: str, payload: dict) -> None:
    ensure_dirs()
    write_plist(installed_plist_path(label), payload)
    bootout(label)
    bootstrap(label)
    enable(label)
    print_text(f"installed {label}")


def uninstall_label(label: str) -> None:
    bootout(label)
    run_launchctl("disable", f"{DOMAIN}/{label}", check=False)
    installed_plist_path(label).unlink(missing_ok=True)


def primary_label(name: str) -> str:
    return f"{LABEL_PREFIX}.recurring.{sanitize_name(name)}"


def recovery_label(name: str) -> str:
    return f"{primary_label(name)}.recovery"


def once_label(name: str) -> str:
    return f"{LABEL_PREFIX}.once.{sanitize_name(name)}"


def label_candidates(name: str) -> list[str]:
    clean = sanitize_name(name)
    return [
        primary_label(clean),
        recovery_label(clean),
        once_label(clean),
    ]


def command_argv(command: str, command_args: list[str], use_open: bool) -> list[str]:
    command_path = os.path.expanduser(command)
    if use_open:
        return ["/usr/bin/open", command_path, *command_args]
    return [command_path, *command_args]


def parse_daily_time(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise SystemExit(f"invalid time '{value}'. expected HH:MM in 24-hour format") from exc
    return parsed.hour, parsed.minute


def parse_once_time(value: str) -> datetime:
    formats = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M")
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed <= datetime.now():
                raise SystemExit("--at must be in the future")
            return parsed
        except ValueError:
            continue
    raise SystemExit(f"invalid datetime '{value}'. expected 'YYYY-MM-DD HH:MM'")


def parse_future_once_time(value: str) -> datetime:
    return parse_once_time(value)


def normalize_command_path(command: str, cwd: str | None = None) -> str:
    base_dir = Path(os.path.expanduser(cwd)).resolve() if cwd else Path.cwd().resolve()
    expanded = Path(os.path.expanduser(command))
    if not expanded.is_absolute():
        expanded = (base_dir / expanded).resolve()
    else:
        expanded = expanded.resolve()
    if not expanded.exists():
        raise SystemExit(f"command path does not exist: {expanded}")
    return str(expanded)


def wrapper_path(label: str) -> Path:
    return GENERATED_JOBS_DIR / f"{label}.sh"


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def write_once_wrapper(label: str, argv: list[str]) -> Path:
    GENERATED_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    script = (
        "#!/bin/zsh\n"
        "set -euo pipefail\n\n"
        + " ".join(shlex_quote(part) for part in argv)
        + "\n"
    )
    path = wrapper_path(label)
    path.write_text(script)
    path.chmod(0o755)
    return path


def build_generated_plist(
    label: str,
    argv: list[str],
    *,
    minute: int | None = None,
    hour: int | None = None,
    month: int | None = None,
    day: int | None = None,
    weekdays: list[int] | None = None,
    calendar_entries: list[dict[str, int]] | None = None,
    cwd: str | None = None,
    stdout_path: str | None = None,
    stderr_path: str | None = None,
    extra_env: list[str] | None = None,
) -> dict:
    if calendar_entries is None:
        if minute is None or hour is None:
            raise SystemExit("minute and hour are required when calendar_entries is not provided")

        def interval_entry(weekday: int | None = None) -> dict[str, int]:
            interval = {"Hour": hour, "Minute": minute}
            if month is not None:
                interval["Month"] = month
            if day is not None:
                interval["Day"] = day
            if weekday is not None:
                interval["Weekday"] = weekday
            return interval

        if weekdays:
            interval: dict | list[dict] = [interval_entry(weekday) for weekday in weekdays]
        else:
            interval = interval_entry()
    else:
        interval = calendar_entries

    payload: dict = {
        "Label": label,
        "ProgramArguments": argv,
        "RunAtLoad": False,
        "StartCalendarInterval": interval,
        "EnvironmentVariables": build_standard_env(extra_env or []),
    }
    if cwd:
        payload["WorkingDirectory"] = os.path.expanduser(cwd)
    if stdout_path:
        payload["StandardOutPath"] = os.path.expanduser(stdout_path)
    if stderr_path:
        payload["StandardErrorPath"] = os.path.expanduser(stderr_path)
    return payload


def parse_weekday_value(value: str) -> int:
    text = value.strip().lower()
    if text in ISO_WEEKDAY_NAMES:
        return ISO_WEEKDAY_NAMES[text]
    try:
        parsed = int(text)
    except ValueError as exc:
        raise SystemExit(f"invalid weekday '{value}'. expected 1-7 or a weekday name") from exc
    if parsed < 1 or parsed > 7:
        raise SystemExit(f"invalid weekday '{value}'. expected 1-7 or a weekday name")
    return parsed


def parse_weekly_spec(value: str) -> tuple[int, str]:
    if "@" not in value:
        raise SystemExit(f"invalid weekly spec '{value}'. expected WEEKDAY@HH:MM")
    weekday_text, time_text = value.split("@", 1)
    weekday = parse_weekday_value(weekday_text)
    parse_daily_time(time_text)
    return weekday, time_text


def normalize_weekdays(values: list[str]) -> list[int]:
    unique = sorted({parse_weekday_value(value) for value in values})
    return unique


def validate_calendar_field(name: str, value: int, minimum: int, maximum: int) -> None:
    if value < minimum or value > maximum:
        raise SystemExit(f"{name} must be between {minimum} and {maximum}")


def validate_calendar_combination(*, year: int | None = None, month: int | None = None, day: int | None = None) -> None:
    if month is None or day is None:
        return
    sample_year = year if year is not None else 2000
    max_day = monthrange(sample_year, month)[1]
    if day > max_day:
        suffix = f" for year {sample_year}" if year is not None else ""
        raise SystemExit(f"invalid calendar date: month {month} does not have day {day}{suffix}")


def recovery_calendar_entries(
    *,
    weekdays: list[int] | None,
    day: int | None,
    month: int | None,
) -> list[dict[str, int]]:
    entries: list[dict[str, int]] = []
    for weekday in weekdays or [None]:
        for minute in (0, 30):
            entry = {"Minute": minute}
            if weekday is not None:
                entry["Weekday"] = weekday
            if day is not None:
                entry["Day"] = day
            if month is not None:
                entry["Month"] = month
            entries.append(entry)
    return entries


def recurring_runner_argv(
    *,
    job: str,
    trigger_kind: str,
    scheduled_time: str,
    day: int | None,
    month: int | None,
    command: str,
    command_args: list[str],
    use_open: bool,
    weekdays: list[int] | None,
) -> list[str]:
    return [
        "python3",
        str(PROJECT_DIR / "tools" / "job_runner.py"),
        "recurring",
        "--job",
        sanitize_name(job),
        "--trigger-kind",
        trigger_kind,
        "--scheduled-time",
        scheduled_time,
        *(["--day", str(day)] if day is not None else []),
        *(["--month", str(month)] if month is not None else []),
        "--command",
        command,
        *(["--open"] if use_open else []),
        *[value for weekday in weekdays or [] for value in ("--weekday", str(weekday))],
        *(["--", *command_args] if command_args else []),
    ]


def once_runner_argv(
    *,
    job: str,
    label: str,
    command: str,
    command_args: list[str],
    use_open: bool,
) -> list[str]:
    return [
        "python3",
        str(PROJECT_DIR / "tools" / "job_runner.py"),
        "once",
        "--job",
        sanitize_name(job),
        "--cleanup-label",
        label,
        "--command",
        command,
        *(["--open"] if use_open else []),
        *(["--", *command_args] if command_args else []),
    ]


def notification_command_args(*, title: str, body: str) -> tuple[str, list[str], bool]:
    script = f'display notification "{body.replace(chr(34), r"\\\"")}" with title "{title.replace(chr(34), r"\\\"")}"'
    return "/usr/bin/osascript", ["-e", script], False


def codex_command_args(
    *,
    prompt: str,
    workspace: str | None,
    job_name: str,
) -> tuple[str, list[str], bool]:
    command = str((PROJECT_DIR / "tools" / "launch_codex_prompt.sh").resolve())
    args = ["--prompt", prompt, "--job-name", job_name]
    if workspace:
        args.extend(["--workspace", workspace])
    return command, args, False


def time_schedule(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def split_command_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    idx = argv.index("--")
    return argv[:idx], argv[idx + 1 :]


def resolve_schedule_config(args: argparse.Namespace) -> dict:
    explicit_fields_used = any(
        value is not None for value in (args.year, args.minute, args.hour, args.day, args.month)
    ) or bool(args.weekday)
    convenience_count = sum(
        bool(value)
        for value in (
            args.time,
            args.daily,
            args.weekdays,
            args.weekly,
            args.at,
        )
    )

    if args.once and args.weekdays:
        raise SystemExit("--once cannot be combined with --weekdays")
    if args.once and args.weekly:
        raise SystemExit("--once cannot be combined with --weekly")
    if args.once and args.at:
        raise SystemExit("--once cannot be combined with --at")
    if args.at and explicit_fields_used:
        raise SystemExit("--at cannot be combined with --year/--minute/--hour/--day/--month/--weekday")
    if args.at and (args.time or args.daily or args.weekdays or args.weekly):
        raise SystemExit("--at cannot be combined with other schedule shortcuts")

    if convenience_count > 1:
        raise SystemExit("choose exactly one of --time, --daily, --weekdays, --weekly, or --at")

    if args.at:
        dt = parse_future_once_time(args.at)
        return {
            "kind": "once",
            "year": dt.year,
            "hour": dt.hour,
            "minute": dt.minute,
            "day": dt.day,
            "month": dt.month,
        }

    if args.weekly:
        if explicit_fields_used:
            raise SystemExit("--weekly cannot be combined with --minute/--hour/--day/--month/--weekday")
        if args.once:
            raise SystemExit("--weekly cannot be combined with --once")
        weekday, time_text = parse_weekly_spec(args.weekly)
        hour, minute = parse_daily_time(time_text)
        return {
            "kind": "recurring",
            "year": None,
            "hour": hour,
            "minute": minute,
            "day": None,
            "month": None,
            "weekdays": [weekday],
            "scheduled_time": time_text,
        }

    if args.weekdays:
        if explicit_fields_used:
            raise SystemExit("--weekdays cannot be combined with --minute/--hour/--day/--month/--weekday")
        if args.once:
            raise SystemExit("--weekdays cannot be combined with --once")
        hour, minute = parse_daily_time(args.weekdays)
        return {
            "kind": "recurring",
            "year": None,
            "hour": hour,
            "minute": minute,
            "day": None,
            "month": None,
            "weekdays": [1, 2, 3, 4, 5],
            "scheduled_time": args.weekdays,
        }

    daily_time = args.daily or args.time
    if daily_time:
        if explicit_fields_used:
            raise SystemExit("--time/--daily cannot be combined with --minute/--hour/--day/--month/--weekday")
        if args.once:
            raise SystemExit("--time/--daily cannot be combined with --once")
        hour, minute = parse_daily_time(daily_time)
        weekdays = [1, 2, 3, 4, 5] if args.weekdays_only else None
        return {
            "kind": "recurring",
            "year": None,
            "hour": hour,
            "minute": minute,
            "day": None,
            "month": None,
            "weekdays": weekdays,
            "scheduled_time": daily_time,
        }

    if explicit_fields_used:
        if args.minute is None or args.hour is None:
            raise SystemExit("--minute and --hour are required when using explicit calendar fields")
        validate_calendar_field("--minute", args.minute, 0, 59)
        validate_calendar_field("--hour", args.hour, 0, 23)
        if args.year is not None:
            validate_calendar_field("--year", args.year, 1970, 9999)
        if args.day is not None:
            validate_calendar_field("--day", args.day, 1, 31)
        if args.month is not None:
            validate_calendar_field("--month", args.month, 1, 12)
        weekdays = normalize_weekdays(args.weekday)
        if args.once:
            if weekdays:
                raise SystemExit("--once cannot be combined with --weekday")
            if args.year is None or args.day is None or args.month is None:
                raise SystemExit("--once with explicit calendar fields requires --year, --month, and --day")
            validate_calendar_combination(year=args.year, month=args.month, day=args.day)
            dt = datetime(args.year, args.month, args.day, args.hour, args.minute)
            if dt <= datetime.now():
                raise SystemExit("explicit one-off schedule must be in the future")
            return {
                "kind": "once",
                "year": args.year,
                "hour": args.hour,
                "minute": args.minute,
                "day": args.day,
                "month": args.month,
            }
        if args.year is not None:
            raise SystemExit("--year is only valid together with --once")
        validate_calendar_combination(month=args.month, day=args.day)
        return {
            "kind": "recurring",
            "year": None,
            "hour": args.hour,
            "minute": args.minute,
            "day": args.day,
            "month": args.month,
            "weekdays": weekdays or None,
            "scheduled_time": time_schedule(args.hour, args.minute),
        }

    raise SystemExit(
        "missing schedule. use --time/--daily/--weekdays/--weekly/--at or explicit calendar fields"
    )


def resolve_existing_labels(name_or_label: str) -> list[str]:
    if name_or_label.startswith(f"{LABEL_PREFIX}."):
        return [name_or_label] if plist_exists(name_or_label) else []

    labels = [label for label in label_candidates(name_or_label) if plist_exists(label)]
    return labels


def resolve_existing_labels_or_die(name_or_label: str) -> list[str]:
    labels = resolve_existing_labels(name_or_label)
    if labels:
        return labels
    raise SystemExit(f"could not resolve job '{name_or_label}'")


def resolve_primary_label(name_or_label: str) -> str:
    if name_or_label.startswith(f"{LABEL_PREFIX}."):
        return name_or_label

    label = primary_label(name_or_label)
    if plist_exists(label):
        return label

    available = ", ".join(resolve_existing_labels(name_or_label))
    if available:
        raise SystemExit(f"job '{name_or_label}' has no primary recurring job. available labels: {available}")
    raise SystemExit(f"could not resolve job '{name_or_label}'")


def list_known_jobs() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    if not LAUNCH_AGENTS_DIR.exists():
        return rows

    for path in sorted(LAUNCH_AGENTS_DIR.glob(f"{LABEL_PREFIX}.*.plist")):
        label = path.stem
        if label.startswith(f"{LABEL_PREFIX}.recurring."):
            base = label.removeprefix(f"{LABEL_PREFIX}.recurring.")
            if base.endswith(".recovery"):
                name = base.removesuffix(".recovery")
                kind = "recovery"
            else:
                name = base
                kind = "recurring"
        elif label.startswith(f"{LABEL_PREFIX}.once."):
            name = label.removeprefix(f"{LABEL_PREFIX}.once.")
            kind = "once"
        else:
            name = label
            kind = "unknown"
        rows.append((name, kind, label))
    return rows


def cmd_list(_: argparse.Namespace) -> None:
    rows = list_known_jobs()
    if not rows:
        print_text("no jobs installed")
        return

    name_width = max(len(name) for name, _, _ in rows)
    kind_width = max(len(kind) for _, kind, _ in rows)
    for name, kind, label in rows:
        print_text(f"{name.ljust(name_width)}  {kind.ljust(kind_width)}  {label}")


def cmd_status(args: argparse.Namespace) -> None:
    if not args.job:
        cmd_list(args)
        return

    label = resolve_primary_label(args.job)
    proc = launchctl_print(label)
    if proc.returncode == 0:
        print_text(proc.stdout)
        return
    print_text(proc.stderr or f"{label} is not loaded")
    raise SystemExit(proc.returncode)


def cmd_enable(args: argparse.Namespace) -> None:
    for label in resolve_existing_labels_or_die(args.job):
        enable(label)
        print_text(f"enabled {label}")


def cmd_disable(args: argparse.Namespace) -> None:
    for label in resolve_existing_labels_or_die(args.job):
        disable(label)
        print_text(f"disabled {label}")


def cmd_restart(args: argparse.Namespace) -> None:
    for label in resolve_existing_labels_or_die(args.job):
        bootout(label)
        bootstrap(label)
        enable(label)
        print_text(f"restarted {label}")


def cmd_run(args: argparse.Namespace) -> None:
    label = resolve_primary_label(args.job)
    kickstart(label)
    print_text(f"triggered {label}")


def cmd_remove(args: argparse.Namespace) -> None:
    labels = [args.job] if args.label else resolve_existing_labels_or_die(args.job)

    for label in labels:
        uninstall_label(label)
        wrapper_path(label).unlink(missing_ok=True)
        print_text(f"removed {label}")


def cmd_schedule(args: argparse.Namespace) -> None:
    name = sanitize_name(args.name)
    command = normalize_command_path(args.command, args.cwd)
    command_args = args.command_args
    config = resolve_schedule_config(args)

    if config["kind"] == "once":
        label = once_label(name)
        argv = once_runner_argv(
            job=name,
            label=label,
            command=command,
            command_args=command_args,
            use_open=args.open,
        )
        wrapper = write_once_wrapper(label, argv)
        payload = build_generated_plist(
            label,
            [str(wrapper)],
            minute=config["minute"],
            hour=config["hour"],
            month=config["month"],
            day=config["day"],
            cwd=args.cwd,
            stdout_path=args.stdout,
            stderr_path=args.stderr,
            extra_env=args.env,
        )
        install_job(label, payload)
        return

    primary = primary_label(name)
    primary_payload = build_generated_plist(
        primary,
        recurring_runner_argv(
            job=name,
            trigger_kind="scheduled",
            scheduled_time=config["scheduled_time"],
            day=config["day"],
            month=config["month"],
            command=command,
            command_args=command_args,
            use_open=args.open,
            weekdays=config["weekdays"],
        ),
        minute=config["minute"],
        hour=config["hour"],
        month=config["month"],
        day=config["day"],
        weekdays=config["weekdays"],
        cwd=args.cwd,
        stdout_path=args.stdout,
        stderr_path=args.stderr,
        extra_env=args.env,
    )
    install_job(primary, primary_payload)

    if args.no_recurring_fallback:
        return

    recovery = recovery_label(name)
    recovery_payload = build_generated_plist(
        recovery,
        recurring_runner_argv(
            job=name,
            trigger_kind="recovery",
            scheduled_time=config["scheduled_time"],
            day=config["day"],
            month=config["month"],
            command=command,
            command_args=command_args,
            use_open=args.open,
            weekdays=config["weekdays"],
        ),
        calendar_entries=recovery_calendar_entries(
            weekdays=config["weekdays"],
            day=config["day"],
            month=config["month"],
        ),
        cwd=args.cwd,
        stdout_path=args.stdout,
        stderr_path=args.stderr,
        extra_env=args.env,
    )
    install_job(recovery, recovery_payload)


def cmd_schedule_once(args: argparse.Namespace) -> None:
    name = sanitize_name(args.name)
    dt = parse_once_time(args.at)
    command = normalize_command_path(args.command, args.cwd)
    command_args = args.command_args
    label = once_label(name)
    argv = once_runner_argv(
        job=name,
        label=label,
        command=command,
        command_args=command_args,
        use_open=args.open,
    )
    wrapper = write_once_wrapper(label, argv)
    payload = build_generated_plist(
        label,
        [str(wrapper)],
        minute=dt.minute,
        hour=dt.hour,
        month=dt.month,
        day=dt.day,
        cwd=args.cwd,
        stdout_path=args.stdout,
        stderr_path=args.stderr,
        extra_env=args.env,
    )
    install_job(label, payload)


def cmd_schedule_codex(args: argparse.Namespace) -> None:
    command, command_args, use_open = codex_command_args(
        prompt=args.prompt,
        workspace=args.workspace,
        job_name=sanitize_name(args.name),
    )
    args.command = command
    args.command_args = command_args
    args.open = use_open
    cmd_schedule(args)


def cmd_schedule_notification(args: argparse.Namespace) -> None:
    command, command_args, use_open = notification_command_args(title=args.title, body=args.body)
    args.command = command
    args.command_args = command_args
    args.open = use_open
    cmd_schedule(args)


def add_schedule_shape_args(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--time", help="Legacy daily execution time in HH:MM")
    cmd.add_argument("--daily", help="Daily execution time in HH:MM")
    cmd.add_argument("--weekdays", help="Weekday execution time in HH:MM")
    cmd.add_argument("--weekly", help="Weekly execution as WEEKDAY@HH:MM, for example mon@09:30")
    cmd.add_argument("--at", help="One-off execution time, 'YYYY-MM-DD HH:MM'")
    cmd.add_argument("--once", action="store_true", help="Treat explicit calendar fields as a one-off schedule")
    cmd.add_argument("--year", type=int, help="Calendar year for explicit one-off schedules")
    cmd.add_argument("--minute", type=int, help="Calendar minute (0-59)")
    cmd.add_argument("--hour", type=int, help="Calendar hour (0-23)")
    cmd.add_argument("--day", type=int, help="Calendar day of month (1-31)")
    cmd.add_argument("--month", type=int, help="Calendar month (1-12)")
    cmd.add_argument(
        "--weekday",
        action="append",
        default=[],
        help="Calendar weekday, repeatable. Accepts 1-7 or names like mon, tue, wed.",
    )


def add_schedule_runtime_args(cmd: argparse.ArgumentParser, *, include_open: bool = True) -> None:
    if include_open:
        cmd.add_argument("--open", action="store_true", help="Run the command through /usr/bin/open")
    cmd.add_argument("--cwd", help="Working directory for the job")
    cmd.add_argument("--stdout", help="StandardOutPath for the job")
    cmd.add_argument("--stderr", help="StandardErrorPath for the job")
    cmd.add_argument("--env", action="append", default=[], help="Extra environment variable, KEY=VALUE")
    cmd.add_argument("--weekdays-only", action="store_true", help="Legacy shorthand for Monday through Friday with --time")
    cmd.add_argument(
        "--no-recurring-fallback",
        action="store_true",
        help="Do not install the paired fallback job that checks every 30 minutes after the scheduled time. Ignored for one-off schedules.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage launchd schedules for agent commands, Codex runs, and macOS notifications.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    job_arg_commands = {
        "status": ("Show launchctl status for a recurring job", cmd_status),
        "enable": ("Enable a job and its companion jobs", cmd_enable),
        "disable": ("Disable a job and its companion jobs", cmd_disable),
        "restart": ("Reload a job and its companion jobs", cmd_restart),
        "run": ("Trigger a recurring job immediately", cmd_run),
        "remove": ("Unload and remove a job and its companion jobs", cmd_remove),
    }
    for name, (help_text, func) in job_arg_commands.items():
        cmd = sub.add_parser(name, help=help_text)
        if name == "status":
            cmd.add_argument("job", nargs="?", help="Job name or exact launchd label")
        else:
            cmd.add_argument("job", help="Job name or exact launchd label")
        if name == "remove":
            cmd.add_argument("--label", action="store_true", help="Treat the value as an exact launchd label")
        cmd.set_defaults(func=func)

    list_cmd = sub.add_parser("list", help="List installed scheduler jobs")
    list_cmd.set_defaults(func=cmd_list)

    schedule = sub.add_parser(
        "schedule",
        help="Create a launchd job from convenience flags or explicit calendar fields",
        epilog="Pass arguments to the scheduled command after '--'. Example: --command /path/to/launcher.sh -- --prompt-file /path/to/prompt.md",
    )
    schedule.add_argument("name", help="Friendly name for the generated job")
    add_schedule_shape_args(schedule)
    schedule.add_argument("--command", required=True, help="Path to the script or file to run; relative paths are normalized at install time")
    add_schedule_runtime_args(schedule)
    schedule.set_defaults(func=cmd_schedule)

    schedule_codex = sub.add_parser(
        "schedule-codex",
        help="Create a schedule that launches a Codex prompt runner",
    )
    schedule_codex.add_argument("name", help="Job name")
    add_schedule_shape_args(schedule_codex)
    schedule_codex.add_argument("--prompt", required=True, help="Prompt text to pass to Codex and store in the scheduled job")
    schedule_codex.add_argument("--workspace", help="Workspace path for the Codex run")
    add_schedule_runtime_args(schedule_codex, include_open=False)
    schedule_codex.set_defaults(func=cmd_schedule_codex, open=False)

    schedule_notification = sub.add_parser(
        "schedule-notification",
        help="Create a schedule that shows a macOS notification",
    )
    schedule_notification.add_argument("name", help="Job name")
    add_schedule_shape_args(schedule_notification)
    schedule_notification.add_argument("--title", required=True, help="Notification title")
    schedule_notification.add_argument("--body", required=True, help="Notification body")
    add_schedule_runtime_args(schedule_notification, include_open=False)
    schedule_notification.set_defaults(func=cmd_schedule_notification, open=False)

    schedule_once = sub.add_parser(
        "schedule-once",
        help="Create a one-time job that removes itself after execution",
        epilog="Pass arguments to the scheduled command after '--'. Example: --command /path/to/launcher.sh -- --prompt-file /path/to/prompt.md",
    )
    schedule_once.add_argument("name", help="Friendly name for the generated job")
    schedule_once.add_argument("--at", required=True, help="Execution time, 'YYYY-MM-DD HH:MM'")
    schedule_once.add_argument("--command", required=True, help="Path to the script or file to run; relative paths are normalized at install time")
    schedule_once.add_argument("--open", action="store_true", help="Run the command through /usr/bin/open")
    schedule_once.add_argument("--cwd", help="Working directory for the job")
    schedule_once.add_argument("--stdout", help="StandardOutPath for the job")
    schedule_once.add_argument("--stderr", help="StandardErrorPath for the job")
    schedule_once.add_argument("--env", action="append", default=[], help="Extra environment variable, KEY=VALUE")
    schedule_once.set_defaults(func=cmd_schedule_once)

    return parser


def main() -> None:
    parser = build_parser()
    parser_argv, command_args = split_command_args(sys.argv[1:])
    args = parser.parse_args(parser_argv)
    args.command_args = command_args
    args.func(args)


if __name__ == "__main__":
    main()
