"""A desktop build must use the SDK/runtime versions declared for delivery."""
import importlib.metadata
from pathlib import Path
import re
import runpy
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


class BuildDependencyTests(unittest.TestCase):
    def pins(self):
        text = (ROOT / 'requirements-dsh.txt').read_text()
        names = ('deepseek-harness-sdk', 'deepseek-harness-runtime-bin')
        return {name: re.search(r'^' + re.escape(name) + r'==([^\s#]+)', text, re.M)[1]
                for name in names}

    def build(self, versions, *, missing=None):
        def version(name):
            if name == missing:
                raise importlib.metadata.PackageNotFoundError(name)
            return versions[name]
        with patch('importlib.metadata.version', side_effect=version), \
                patch.object(sys, 'argv', ['build_linux.py', '--backend-only']), \
                patch('subprocess.run') as execute:
            self.execute = execute
            runpy.run_path(str(ROOT / 'tools/build_linux.py'), run_name='__main__')
        return execute

    def test_declared_versions_allow_the_existing_freezer_command(self):
        execute = self.build(self.pins())
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0][:3], [sys.executable, '-m', 'PyInstaller'])

    def test_other_sdk_is_rejected_before_freezer_or_output_changes(self):
        versions = self.pins()
        versions['deepseek-harness-sdk'] = '0.0.0'
        with self.assertRaisesRegex(RuntimeError, 'deepseek-harness-sdk'):
            self.build(versions)
        self.execute.assert_not_called()

    def test_missing_runtime_is_rejected_before_freezer(self):
        with self.assertRaisesRegex(RuntimeError, 'deepseek-harness-runtime-bin'):
            self.build(self.pins(), missing='deepseek-harness-runtime-bin')
        self.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
