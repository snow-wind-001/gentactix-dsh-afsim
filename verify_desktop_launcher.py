"""Keep an active extracted AppImage usable after another instance exits."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from tools import install_linux


class DesktopLauncherTests(unittest.TestCase):
    def test_second_launch_does_not_remove_running_instance_resources(self):
        with tempfile.TemporaryDirectory(prefix='gentactix-launcher-') as temporary:
            root = Path(temporary)
            source = root / 'fake.AppImage'
            # Model the observed runtime boundary: extraction is shared, while
            # a second Electron process can exit before the first process does.
            source.write_text(f'#!{sys.executable}\n' + textwrap.dedent('''\
                import os, shutil, sys, time
                from pathlib import Path
                root = Path(os.environ['GTX_LAUNCH_TEST_STATE'])
                payload = root / 'shared-extraction'
                try:
                    if os.environ['GTX_LAUNCH_TEST_ROLE'] == 'first':
                        payload.mkdir(exist_ok=True)
                        (payload / 'battle.json').write_text('available')
                        (root / 'ready').touch()
                        deadline = time.monotonic() + 10
                        while not (root / 'release').exists():
                            if time.monotonic() > deadline:
                                sys.exit(90)
                            time.sleep(.02)
                        sys.exit(0 if (payload / 'battle.json').exists() else 91)
                finally:
                    if os.environ.get('NO_CLEANUP') != '1':
                        shutil.rmtree(payload, ignore_errors=True)
                '''))
            source.chmod(0o755)
            data = root / 'user data'
            desktop = root / 'Desktop'
            with patch.dict(os.environ, {'XDG_DATA_HOME': str(data)}), \
                    patch.object(sys, 'argv', ['install_linux.py', str(source)]), \
                    patch.object(install_linux.shutil, 'which', return_value=None), \
                    patch.object(install_linux.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess([], 0)), \
                    patch.object(install_linux.subprocess, 'check_output',
                                 return_value=str(desktop)), \
                    contextlib.redirect_stdout(io.StringIO()):
                install_linux.main()
            launcher = data / 'GenTactix-DSH/launch.sh'
            env = dict(os.environ, GTX_LAUNCH_TEST_STATE=str(root),
                       GTX_LAUNCH_TEST_ROLE='first')
            env.pop('NO_CLEANUP', None)
            first = subprocess.Popen([str(launcher)], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not (root / 'ready').exists():
                    self.assertIsNone(first.poll(), 'First application exited early')
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.02)
                second = subprocess.run([str(launcher)],
                                        env=dict(env, GTX_LAUNCH_TEST_ROLE='second'),
                                        capture_output=True, timeout=5)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertTrue((root / 'shared-extraction/battle.json').is_file(),
                                'Second launch removed the active application resources')
            finally:
                (root / 'release').touch()
                first.communicate(timeout=5)
            self.assertEqual(first.returncode, 0,
                             'Running application lost resources after second launch')


if __name__ == '__main__':
    unittest.main()
