import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_PATH = REPO_ROOT / "tools" / "scheduler.py"


def load_scheduler_module():
    spec = importlib.util.spec_from_file_location("scheduler_under_test", SCHEDULER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scheduler = load_scheduler_module()

    def parse_schedule_args(self, *argv):
        parser = self.scheduler.build_parser()
        parser_argv, command_args = self.scheduler.split_command_args(
            ["schedule", "demo-job", *argv, "--command", "/bin/true"]
        )
        args = parser.parse_args(parser_argv)
        args.command_args = command_args
        return args

    def parse_codex_args(self, *argv):
        parser = self.scheduler.build_parser()
        args = parser.parse_args(["schedule-codex", "demo-job", *argv, "--prompt", "Solve the task"])
        args.command_args = []
        return args

    def parse_notification_args(self, *argv):
        parser = self.scheduler.build_parser()
        args = parser.parse_args(
            ["schedule-notification", "demo-job", *argv, "--title", "Title", "--body", "Body"]
        )
        args.command_args = []
        return args

    def test_normalize_command_path_makes_relative_command_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = tmp_path / "run.sh"
            command.write_text("#!/bin/zsh\nexit 0\n", encoding="utf-8")
            normalized = self.scheduler.normalize_command_path("run.sh", str(tmp_path))
        self.assertEqual(normalized, str(command.resolve()))

    def test_normalize_command_path_rejects_missing_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                self.scheduler.normalize_command_path("missing.sh", tmp)
        self.assertIn("command path does not exist", str(ctx.exception))

    def test_schedule_config_supports_explicit_once_with_year(self):
        args = self.parse_schedule_args(
            "--once",
            "--year",
            "2099",
            "--month",
            "12",
            "--day",
            "31",
            "--hour",
            "9",
            "--minute",
            "30",
        )
        config = self.scheduler.resolve_schedule_config(args)
        self.assertEqual(
            config,
            {
                "kind": "once",
                "year": 2099,
                "hour": 9,
                "minute": 30,
                "day": 31,
                "month": 12,
            },
        )

    def test_schedule_config_rejects_invalid_month_day_combination(self):
        args = self.parse_schedule_args("--month", "4", "--day", "31", "--hour", "9", "--minute", "30")
        with self.assertRaises(SystemExit) as ctx:
            self.scheduler.resolve_schedule_config(args)
        self.assertIn("invalid calendar date", str(ctx.exception))

    def test_schedule_config_rejects_year_without_once(self):
        args = self.parse_schedule_args("--year", "2099", "--month", "12", "--day", "31", "--hour", "9", "--minute", "30")
        with self.assertRaises(SystemExit) as ctx:
            self.scheduler.resolve_schedule_config(args)
        self.assertEqual(str(ctx.exception), "--year is only valid together with --once")

    def test_recovery_calendar_entries_include_day_and_month_constraints(self):
        entries = self.scheduler.recovery_calendar_entries(weekdays=[1, 5], day=15, month=4)
        self.assertEqual(
            entries,
            [
                {"Minute": 0, "Weekday": 1, "Day": 15, "Month": 4},
                {"Minute": 30, "Weekday": 1, "Day": 15, "Month": 4},
                {"Minute": 0, "Weekday": 5, "Day": 15, "Month": 4},
                {"Minute": 30, "Weekday": 5, "Day": 15, "Month": 4},
            ],
        )

    def test_recurring_runner_argv_no_longer_exposes_slot_key_argument(self):
        argv = self.scheduler.recurring_runner_argv(
            job="demo-job",
            trigger_kind="scheduled",
            scheduled_time="09:30",
            day=None,
            month=None,
            command="/bin/true",
            command_args=["--prompt-file", "/tmp/prompt.md"],
            use_open=False,
            weekdays=[1, 3],
        )
        self.assertNotIn("--slot-key", argv)
        self.assertIn("--scheduled-time", argv)
        self.assertIn("--", argv)

    def test_command_argv_appends_command_args(self):
        argv = self.scheduler.command_argv("/bin/echo", ["hello", "world"], False)
        self.assertEqual(argv, ["/bin/echo", "hello", "world"])

    def test_once_runner_argv_includes_cleanup_label(self):
        argv = self.scheduler.once_runner_argv(
            job="demo-job",
            label="com.agent-scheduler.once.demo-job",
            command="/bin/true",
            command_args=["--x"],
            use_open=False,
        )
        self.assertIn("--cleanup-label", argv)
        self.assertIn("com.agent-scheduler.once.demo-job", argv)

    def test_codex_command_args_use_bundled_launcher(self):
        command, command_args, use_open = self.scheduler.codex_command_args(
            prompt="Solve the task",
            workspace="/tmp/workspace",
            job_name="demo-job",
        )
        self.assertTrue(command.endswith("/tools/launch_codex_prompt.sh"))
        self.assertEqual(
            command_args,
            ["--prompt", "Solve the task", "--job-name", "demo-job", "--workspace", "/tmp/workspace"],
        )
        self.assertFalse(use_open)

    def test_notification_command_args_emit_osascript(self):
        command, command_args, use_open = self.scheduler.notification_command_args(title="Title", body="Body")
        self.assertEqual(command, "/usr/bin/osascript")
        self.assertEqual(command_args, ["-e", 'display notification "Body" with title "Title"'])
        self.assertFalse(use_open)

    def test_split_command_args_extracts_tail_after_separator(self):
        parser_argv, command_args = self.scheduler.split_command_args(
            ["schedule", "demo-job", "--command", "/bin/true", "--", "--prompt-file", "/tmp/prompt.md"]
        )
        self.assertEqual(parser_argv, ["schedule", "demo-job", "--command", "/bin/true"])
        self.assertEqual(command_args, ["--prompt-file", "/tmp/prompt.md"])

    def test_write_once_wrapper_no_longer_uses_shell_trap_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_dir = Path(tmp)
            original_dir = self.scheduler.GENERATED_JOBS_DIR
            self.scheduler.GENERATED_JOBS_DIR = generated_dir
            try:
                path = self.scheduler.write_once_wrapper("com.agent-scheduler.once.demo", ["python3", "/tmp/task.py"])
                content = path.read_text(encoding="utf-8")
            finally:
                self.scheduler.GENERATED_JOBS_DIR = original_dir

        self.assertNotIn("trap cleanup EXIT", content)
        self.assertIn("'python3' '/tmp/task.py'", content)

    def test_schedule_codex_parser_exposes_prompt(self):
        args = self.parse_codex_args("--daily", "09:30")
        self.assertEqual(args.prompt, "Solve the task")
        self.assertEqual(args.daily, "09:30")
        self.assertFalse(args.open)

    def test_schedule_notification_parser_exposes_title_and_body(self):
        args = self.parse_notification_args("--daily", "09:30")
        self.assertEqual(args.title, "Title")
        self.assertEqual(args.body, "Body")
        self.assertFalse(args.open)


if __name__ == "__main__":
    unittest.main()
