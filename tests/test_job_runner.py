import importlib.util
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
JOB_RUNNER_PATH = REPO_ROOT / "tools" / "job_runner.py"


def load_job_runner_module():
    spec = importlib.util.spec_from_file_location("job_runner_under_test", JOB_RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class JobRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job_runner = load_job_runner_module()

    def test_slot_key_is_derived_from_scheduled_time(self):
        self.assertEqual(self.job_runner.slot_key("09:30"), "0930")

    def test_should_skip_calendar_day_honors_month_and_day(self):
        now = datetime(2026, 4, 15, 10, 0)
        self.assertFalse(self.job_runner.should_skip_calendar_day(now, 15, 4))
        self.assertTrue(self.job_runner.should_skip_calendar_day(now, 16, 4))
        self.assertTrue(self.job_runner.should_skip_calendar_day(now, 15, 5))

    def test_should_skip_recovery_before_scheduled_time(self):
        now = datetime(2026, 4, 15, 9, 0)
        self.assertTrue(self.job_runner.should_skip_recovery(now, 9, 30))
        self.assertFalse(self.job_runner.should_skip_recovery(now, 9, 0))

    def test_command_argv_appends_command_args(self):
        argv = self.job_runner.command_argv("/bin/echo", ["hello", "world"], False)
        self.assertEqual(argv, ["/bin/echo", "hello", "world"])

    def test_split_command_args_extracts_tail_after_separator(self):
        parser_argv, command_args = self.job_runner.split_command_args(
            ["once", "--job", "demo", "--command", "/bin/echo", "--", "--prompt-file", "/tmp/prompt.md"]
        )
        self.assertEqual(parser_argv, ["once", "--job", "demo", "--command", "/bin/echo"])
        self.assertEqual(command_args, ["--prompt-file", "/tmp/prompt.md"])

    def test_cleanup_once_job_ignores_empty_label(self):
        self.assertEqual(self.job_runner.cleanup_once_job(None), {"attempted": False, "reason": "missing label"})

    def test_cleanup_once_job_unlinks_plist_and_defers_launchctl_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch_agents = Path(tmp)
            plist_path = launch_agents / 'com.agent-scheduler.once.demo.plist'
            plist_path.write_text('plist', encoding='utf-8')
            original_dir = self.job_runner.LAUNCH_AGENTS_DIR
            self.job_runner.LAUNCH_AGENTS_DIR = launch_agents
            proc = mock.Mock(pid=4321)
            try:
                with mock.patch.object(self.job_runner.subprocess, 'Popen', return_value=proc) as popen_mock:
                    info = self.job_runner.cleanup_once_job('com.agent-scheduler.once.demo')
            finally:
                self.job_runner.LAUNCH_AGENTS_DIR = original_dir

        self.assertFalse(plist_path.exists())
        self.assertIsNone(info['unlink_error'])
        self.assertFalse(info['plist_exists_after_unlink'])
        self.assertEqual(info['deferred_cleanup_pid'], 4321)
        popen_args = popen_mock.call_args.args[0]
        self.assertEqual(popen_args[:2], ['/bin/sh', '-c'])
        self.assertIn(str(plist_path), popen_args[2])
        self.assertIn(f'{self.job_runner.DOMAIN}/com.agent-scheduler.once.demo', popen_args[2])


if __name__ == "__main__":
    unittest.main()
