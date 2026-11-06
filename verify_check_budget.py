"""The offline driver times out real child checks without hiding later failures."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import verify_all as driver


class CheckBudgetTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.output = self.root / 'results'
        (self.root / 'verify_a.py').write_text('print("first check")\n')
        (self.root / 'verify_b.py').write_text('print("later check completed")\n')
        (self.root / 'measure_turn_degradation.py').write_text('print("measurement fixture")\n')
        (self.root / 'live_adjudication_probe.py').write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'Path(sys.argv[sys.argv.index("--out")+1]).write_text(json.dumps({"checks":'
            '{"movement_violations":True,"engagement_overreach":True,'
            '"supply_narrative_hits":True,"fingerprint_stable":True}}))\n')

    def run_driver(self, args):
        real_run = subprocess.run
        budgets = []

        def run(command, **kwargs):
            budgets.append(kwargs['timeout'])
            # Dependency installation is outside this child-process fixture.
            if command[1:] == ['-m', 'pip', 'check']:
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with patch.object(driver, 'ROOT', self.root), patch.object(driver, 'OUTPUT', self.output), \
                patch.object(driver.sys, 'argv', ['verify_all.py', *args]), \
                patch.object(driver.subprocess, 'run', side_effect=run), \
                contextlib.redirect_stdout(io.StringIO()):
            code = driver.main()
        return code, json.loads((self.output / 'results.json').read_text()), budgets

    def test_custom_budget_terminates_only_the_slow_check_and_keeps_running(self):
        (self.root / 'verify_a.py').write_text('import time\ntime.sleep(2)\nprint("too late")\n')
        code, result, budgets = self.run_driver(['--check-timeout', '0.5'])
        self.assertEqual(code, 1)
        self.assertEqual(result['failed'], 1)
        slow = next(r for r in result['results'] if r['name'] == 'verify_a')
        later = next(r for r in result['results'] if r['name'] == 'verify_b')
        self.assertIn('timed out', slow['error'])
        self.assertNotIn('too late', (self.output / 'verify_a.log').read_text())
        self.assertEqual(later['exit_code'], 0)
        self.assertIn('later check completed', (self.output / 'verify_b.log').read_text())
        self.assertTrue(all(value == 0.5 for value in budgets))
        self.assertEqual(result['check_timeout_seconds'], 0.5)

    def test_invalid_budgets_reject_before_creating_output_or_spawning_checks(self):
        for value in ('0', '-1', 'nan', 'inf', 'not-a-number'):
            with self.subTest(value=value), patch.object(driver, 'OUTPUT', self.output), \
                    patch.object(driver.sys, 'argv', ['verify_all.py', '--check-timeout', value]), \
                    patch.object(driver.subprocess, 'run', side_effect=AssertionError('No child expected')), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                driver.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(self.output.exists())

    def test_larger_default_preserves_assertion_failure_and_runs_remaining_checks(self):
        (self.root / 'verify_a.py').write_text('raise AssertionError("intentional domain failure")\n')
        code, result, budgets = self.run_driver([])
        self.assertEqual(code, 1)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(all(value == 600 for value in budgets))
        self.assertEqual(result['check_timeout_seconds'], 600)
        self.assertIn('intentional domain failure', (self.output / 'verify_a.log').read_text())
        self.assertEqual(next(r for r in result['results'] if r['name'] == 'verify_b')['exit_code'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
