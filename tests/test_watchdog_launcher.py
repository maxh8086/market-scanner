"""Static checks on the watchdog PowerShell launcher, the task registration script and start.ps1.

Text only: nothing is executed, no docker, no Task Scheduler.
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "watchdog.ps1"
REGISTER = REPO_ROOT / "scripts" / "register_watchdog_task.ps1"
START = REPO_ROOT / "start.ps1"


def _code_lines(text):
    """Return the code of a PowerShell file: block comments and whole-line comments removed."""
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _start_check_block(text):
    begin = text.index("# Warning only: the collector watchdog")
    end = text.index('Write-Stage "Done"', begin)
    return text[begin:end]


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.launcher_code = _code_lines(cls.launcher)

    def test_files_exist(self):
        self.assertTrue(LAUNCHER.is_file())
        self.assertTrue(REGISTER.is_file())

    def test_strict_mode_and_named_mutex(self):
        self.assertIn("Set-StrictMode", self.launcher)
        self.assertIn("Global\\MarketScannerWatchdog", self.launcher)
        self.assertIn("System.Threading.Mutex", self.launcher)

    def test_already_running_exits_zero(self):
        self.assertIn("exit 0", self.launcher_code)

    def test_runs_the_module_with_the_project_venv(self):
        self.assertIn(".venv\\Scripts\\python.exe", self.launcher_code)
        self.assertIn("-m scanner.watchdog", self.launcher_code)

    def test_never_reads_dot_env(self):
        self.assertNotIn(".env", self.launcher_code)
        self.assertNotRegex(self.launcher_code, r"(Get-Content|ReadAll\w*|Import-\w+)[^\n]*\.env")

    def test_token_comes_from_env_or_user_variable_only(self):
        self.assertIn("WATCHDOG_TOKEN_FILE", self.launcher_code)
        self.assertIn("GetEnvironmentVariable('WATCHDOG_TOKEN_FILE', 'User')", self.launcher_code)

    def test_no_docker_start_process(self):
        self.assertNotRegex(self.launcher_code, r"Start-Process[^\n]*docker")
        self.assertNotIn("Start-Process", self.launcher_code)

    def test_never_stops_containers(self):
        self.assertNotRegex(self.launcher_code, r"docker\s+(stop|rm|compose\s+(down|stop))")


class RegisterScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = REGISTER.read_text(encoding="utf-8")
        cls.code = _code_lines(cls.text)

    def test_strict_mode_and_task_name(self):
        self.assertIn("Set-StrictMode", self.text)
        self.assertIn("$TaskName = 'MarketScannerWatchdog'", self.text)

    def test_supports_whatif_and_unregister(self):
        self.assertIn("SupportsShouldProcess", self.code)
        self.assertIn("[switch]$Unregister", self.code)
        self.assertIn("-WhatIf", self.text)
        self.assertIn("-Unregister", self.text)

    def test_register_is_behind_should_process(self):
        register_at = self.code.index("Register-ScheduledTask")
        guard_at = self.code.index("ShouldProcess($TaskName, 'Register")
        self.assertLess(guard_at, register_at)

    def test_action_and_restart_policy(self):
        self.assertIn("-NoProfile -ExecutionPolicy Bypass -File", self.code)
        self.assertIn("watchdog.ps1", self.code)
        self.assertIn("-RestartCount 3", self.code)
        self.assertIn("-AtLogOn", self.code)

    def test_header_says_the_user_runs_it(self):
        self.assertIn("Run by you, not by Claude or start.ps1", self.text)

    def test_never_starts_docker_or_reads_dot_env(self):
        self.assertNotIn("Start-Process", self.code)
        self.assertNotIn(".env", self.code)


class StartScriptCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = START.read_text(encoding="utf-8")
        cls.block = _start_check_block(cls.text)
        cls.block_code = _code_lines(cls.block)

    def test_check_exists_after_the_services_start(self):
        services_at = self.text.index("'compose', 'up', '-d', 'ui', 'collector', 'server'")
        check_at = self.text.index("# Warning only: the collector watchdog")
        self.assertLess(services_at, check_at)

    def test_check_never_calls_exit(self):
        self.assertNotRegex(self.block_code, r"\bexit\b")

    def test_check_never_starts_or_registers_the_watchdog(self):
        self.assertNotIn("Start-Process", self.block_code)
        self.assertNotIn("Register-ScheduledTask", self.block_code)
        self.assertNotIn("scanner.watchdog", re.sub(r"'\*scanner\.watchdog\*'", "", self.block_code))
        self.assertNotRegex(self.block_code, r"&\s*\$?\(?\s*['\"]?[^\n]*watchdog\.ps1")

    def test_check_names_both_ways_to_start(self):
        self.assertIn("scripts\\watchdog.ps1", self.block)
        self.assertIn("scripts\\register_watchdog_task.ps1", self.block)

    def test_check_looks_for_mutex_or_process(self):
        self.assertIn("Global\\MarketScannerWatchdog", self.block_code)
        self.assertIn("scanner.watchdog", self.block_code)

    def test_warning_is_one_yellow_line(self):
        self.assertEqual(self.block.count("Write-Host"), 1)
        self.assertIn("-ForegroundColor Yellow", self.block)


if __name__ == "__main__":
    unittest.main()
