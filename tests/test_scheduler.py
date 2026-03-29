import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
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
        args = parser.parse_args(
            ["schedule-notification", "demo-job", *argv, "--title", "Title", "--body", "Body"]
        )
        args.command_args = []
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

    def parse_edit_args(self, *argv):
        parser = self.scheduler.build_parser()
        return parser.parse_args(["edit", "demo-job", *argv])

    def parse_simple_command(self, name):
        parser = self.scheduler.build_parser()
        return parser.parse_args([name])

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
        current_year = self.scheduler.datetime.now().year
        args = self.parse_schedule_args(
            "--once",
            "--year",
            str(current_year),
            "--month",
            "12",
            "--day",
            "31",
            "--hour",
            "23",
            "--minute",
            "59",
        )
        config = self.scheduler.resolve_schedule_config(args)
        self.assertEqual(
            config,
            {
                "kind": "once",
                "year": current_year,
                "hour": 23,
                "minute": 59,
                "day": 31,
                "month": 12,
            },
        )

    def test_build_generated_plist_omits_year_for_once_jobs(self):
        payload = self.scheduler.build_generated_plist(
            'com.agent-scheduler.once.demo',
            ['/bin/true'],
            minute=30,
            hour=9,
            month=12,
            day=31,
        )
        interval = payload['StartCalendarInterval']
        self.assertNotIn('Year', interval)
        self.assertEqual(interval['Month'], 12)
        self.assertEqual(interval['Day'], 31)

    def test_schedule_config_from_payload_ignores_year_for_once_jobs(self):
        config = self.scheduler.schedule_config_from_payload(
            'com.agent-scheduler.once.demo',
            {
                'StartCalendarInterval': {
                    'Year': 2099,
                    'Month': 12,
                    'Day': 31,
                    'Hour': 9,
                    'Minute': 30,
                }
            },
        )
        self.assertIsNone(config['year'])
        self.assertEqual(config['month'], 12)
        self.assertEqual(config['day'], 31)

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

    def test_schedule_config_rejects_at_in_future_year(self):
        next_year = self.scheduler.datetime.now().year + 1
        args = self.parse_schedule_args("--at", f"{next_year}-12-31 09:30")
        with self.assertRaises(SystemExit) as ctx:
            self.scheduler.resolve_schedule_config(args)
        self.assertEqual(str(ctx.exception), "one-off --at schedules must be within the current calendar year")

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
        self.assertEqual(argv[0], self.scheduler.RUNNER_PYTHON)
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
        self.assertEqual(argv[0], self.scheduler.RUNNER_PYTHON)
        self.assertIn("--cleanup-label", argv)
        self.assertIn("com.agent-scheduler.once.demo-job", argv)

    def test_codex_command_args_use_inline_prompt(self):
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

    def test_upsert_env_replaces_existing_value(self):
        env = self.scheduler.upsert_env(["A=1", "AGENT_SCHEDULER_PROMPT=old"], "AGENT_SCHEDULER_PROMPT", "new")
        self.assertEqual(env, ["A=1", "AGENT_SCHEDULER_PROMPT=new"])

    def test_stale_once_labels_only_returns_unloaded_one_off_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch_agents = Path(tmp)
            original_dir = self.scheduler.LAUNCH_AGENTS_DIR
            self.scheduler.LAUNCH_AGENTS_DIR = launch_agents
            try:
                for label in [
                    'com.agent-scheduler.once.stale-job',
                    'com.agent-scheduler.once.active-job',
                    'com.agent-scheduler.recurring.keep-job',
                ]:
                    (launch_agents / f'{label}.plist').write_text('plist', encoding='utf-8')
                original_print = self.scheduler.launchctl_print
                self.scheduler.launchctl_print = lambda label: type('Proc', (), {'returncode': 0 if label == 'com.agent-scheduler.once.active-job' else 113})()
                try:
                    labels = self.scheduler.stale_once_labels()
                finally:
                    self.scheduler.launchctl_print = original_print
            finally:
                self.scheduler.LAUNCH_AGENTS_DIR = original_dir

        self.assertEqual(labels, ['com.agent-scheduler.once.stale-job'])

    def test_remove_all_parser_is_exposed(self):
        args = self.parse_simple_command('remove-all')
        self.assertIs(args.func, self.scheduler.cmd_remove_all)

    def test_prune_once_parser_is_exposed(self):
        args = self.parse_simple_command('prune-once')
        self.assertIs(args.func, self.scheduler.cmd_prune_once)

    def test_get_time_parser_is_exposed(self):
        parser = self.scheduler.build_parser()
        args = parser.parse_args(['get-time', 'demo-job'])
        self.assertEqual(args.job, 'demo-job')
        self.assertIs(args.func, self.scheduler.cmd_get_time)

    def test_get_time_prints_daily_schedule(self):
        original = self.scheduler.inspect_existing_job
        self.scheduler.inspect_existing_job = lambda job: {
            'config': {
                'kind': 'recurring',
                'scheduled_time': '09:30',
                'weekdays': None,
                'day': None,
                'month': None,
                'hour': 9,
                'minute': 30,
            }
        }
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                self.scheduler.cmd_get_time(type('Args', (), {'job': 'demo-job'})())
        finally:
            self.scheduler.inspect_existing_job = original
        self.assertEqual(out.getvalue(), 'daily 09:30\n')

    def test_get_time_prints_once_schedule(self):
        original = self.scheduler.inspect_existing_job
        self.scheduler.inspect_existing_job = lambda job: {
            'config': {
                'kind': 'once',
                'day': 29,
                'month': 3,
                'hour': 20,
                'minute': 15,
            }
        }
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                self.scheduler.cmd_get_time(type('Args', (), {'job': 'demo-job'})())
        finally:
            self.scheduler.inspect_existing_job = original
        self.assertEqual(out.getvalue(), 'once 03-29 20:15\n')

    def test_get_prompt_reads_prompt_from_installed_plist(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch_agents = Path(tmp)
            original_dir = self.scheduler.LAUNCH_AGENTS_DIR
            self.scheduler.LAUNCH_AGENTS_DIR = launch_agents
            label = self.scheduler.primary_label("demo-job")
            payload = self.scheduler.build_generated_plist(
                label,
                ["/bin/true"],
                minute=30,
                hour=9,
                extra_env=[f"{self.scheduler.PROMPT_ENV_KEY}=Solve the task"],
            )
            self.scheduler.write_plist(self.scheduler.installed_plist_path(label), payload)
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    self.scheduler.cmd_get_prompt(type("Args", (), {"job": "demo-job"})())
            finally:
                self.scheduler.LAUNCH_AGENTS_DIR = original_dir

        self.assertEqual(out.getvalue(), "Solve the task\n")

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
            ["placeholder", "demo-job", "--command", "/bin/true", "--", "--prompt-file", "/tmp/prompt.md"]
        )
        self.assertEqual(parser_argv, ["placeholder", "demo-job", "--command", "/bin/true"])
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
        self.assertIn("'/tmp/task.py'", content)

    def test_schedule_codex_parser_exposes_prompt(self):
        args = self.parse_codex_args("--daily", "09:30")
        self.assertEqual(args.prompt, "Solve the task")
        self.assertEqual(args.daily, "09:30")
        self.assertFalse(args.open)

    def test_edit_parser_accepts_prompt_and_daily(self):
        args = self.parse_edit_args("--daily", "10:15", "--prompt", "Updated prompt")
        self.assertEqual(args.daily, "10:15")
        self.assertEqual(args.prompt, "Updated prompt")

    def test_schedule_notification_parser_exposes_title_and_body(self):
        args = self.parse_notification_args("--daily", "09:30")
        self.assertEqual(args.title, "Title")
        self.assertEqual(args.body, "Body")
        self.assertFalse(args.open)


    def test_build_codex_prompt_adds_session_instructions(self):
        prompt = self.scheduler.build_codex_prompt("Solve the task", recurring=False)
        self.assertIn("AGENTS.md", prompt)
        self.assertIn("workspace-local instructions", prompt)
        self.assertIn("SESSIONS/", prompt)
        self.assertIn("save the whole conversation", prompt)
        self.assertNotIn("MEMORY/", prompt)
        self.assertTrue(prompt.endswith("Task:\nSolve the task"))

    def test_build_codex_prompt_adds_memory_instructions_for_recurring_jobs(self):
        prompt = self.scheduler.build_codex_prompt("Solve the task", recurring=True)
        self.assertIn("SESSIONS/", prompt)
        self.assertIn("MEMORY/", prompt)
        self.assertIn("most recent prior date", prompt)
        self.assertTrue(prompt.endswith("Task:\nSolve the task"))


if __name__ == "__main__":
    unittest.main()
