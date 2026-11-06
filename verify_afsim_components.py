"""Project-local AFSIM launch contracts; real runtime validation is separate."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


class AfsimComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('afsim_launch', Path(__file__).parent / 'tools/afsim/launch.py')
        cls.launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.launch)

    def test_windows_uses_native_runtime_without_wine(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = self.launch.layout(Path(tmp))
            cmd = self.launch.mission_command(layout, ['-h'], platform='win32')
            self.assertEqual(cmd, [str(layout['mission']), '-h'])

    def test_linux_uses_project_local_compatibility_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = self.launch.layout(Path(tmp))
            cmd = self.launch.mission_command(layout, ['case.afsim'], platform='linux')
            self.assertEqual(cmd, [str(layout['wine']), str(layout['mission']), 'case.afsim'])
            self.assertTrue(all(Path(cmd[i]).is_relative_to(Path(tmp)) for i in (0, 1)))

    def test_environment_is_detached_and_stores_state_inside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = {'PATH': '/usr/bin', 'HOME': '/preserve-me', 'DEEPSEEK_API_KEY': 'private', 'DSH_SYSTEM_PROMPT': 'private'}
            before = copy.deepcopy(original)
            layout = self.launch.layout(Path(tmp))
            env = self.launch.execution_env(layout, original, platform='linux')
            self.assertEqual(original, before)
            self.assertEqual(env['HOME'], '/preserve-me')
            self.assertNotIn('DEEPSEEK_API_KEY', env)
            self.assertNotIn('DSH_SYSTEM_PROMPT', env)
            self.assertTrue(Path(env['WINEPREFIX']).is_relative_to(Path(tmp)))

    def test_mcp_uses_existing_upstream_transport_and_separate_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = self.launch.layout(Path(tmp))
            env = self.launch.mcp_env(layout, {}, platform='linux')
            self.assertEqual(Path(env['AFSIM_ROOT']), layout['runtime'])
            self.assertTrue(Path(env['AFSIM_MCP_CONFIG_DIR']).is_relative_to(Path(tmp)))
            self.assertTrue(Path(env['AFSIM_MCP_STATE_DIR']).is_relative_to(Path(tmp)))
            self.assertEqual(Path(env['AFSIM_MISSION_PATH']), layout['proxy'])

    def test_missing_runtime_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = self.launch.status(self.launch.layout(Path(tmp)), platform='win32')
            self.assertFalse(value['available'])
            self.assertIn('mission.exe', value['missing'][0])

    def test_upstream_sources_have_license_and_pinned_commit(self):
        import json
        root = Path(__file__).parent / 'vendor/afsim'
        lock = json.loads((root / 'dependencies.lock.json').read_text())
        for component in lock['components']:
            if component.get('license') == 'MIT':
                self.assertEqual(len(component['commit']), 40)
                self.assertTrue((root / component['license_file']).is_file())


if __name__ == '__main__':
    unittest.main()
