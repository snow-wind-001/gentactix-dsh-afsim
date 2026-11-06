"""Build the bundled Python backend, then Linux AppImage and portable archive.

Run with the Python environment containing requirements.txt, requirements-dsh.txt
and PyInstaller. No local .env, model key or session cache is packaged.
"""
from pathlib import Path
from importlib import metadata
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def validate_runtime_dependencies():
    """Reject packaging an untested SDK instead of trusting pip's ABI check."""
    lines = (ROOT / 'requirements-dsh.txt').read_text(encoding='utf-8').splitlines()
    for package in ('deepseek-harness-sdk', 'deepseek-harness-runtime-bin'):
        pins = [line.split('==', 1)[1].strip() for line in lines
                if line.startswith(package + '==')]
        if len(pins) != 1:
            raise RuntimeError(package + ' must have one exact delivery version')
        try:
            installed = metadata.version(package)
        except metadata.PackageNotFoundError as exc:
            raise RuntimeError(package + ' is missing; install requirements-dsh.txt before building') from exc
        if installed != pins[0]:
            raise RuntimeError(f'{package}: installed {installed}, declared {pins[0]}; '
                               'use the declared build environment before packaging')


import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backend-only', action='store_true', help='Freeze Python without rebuilding Electron artifacts')
args = parser.parse_args()
validate_runtime_dependencies()
env = os.environ.copy()
# ROS/system PYTHONPATH can leak unrelated packages into a frozen application.
env.pop('PYTHONPATH', None)
env['PYTHONNOUSERSITE'] = '1'
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
           '--name', 'gentactix-backend', '--distpath', str(ROOT / 'dist-backend'),
           '--workpath', str(ROOT / 'build-backend'), '--specpath', str(ROOT / 'build-backend'),
           '--paths', str(ROOT), '--collect-all', 'deepseek_harness',
           '--collect-all', 'deepseek_harness_runtime', '--collect-all', 'global_land_mask',
           '--copy-metadata', 'deepseek-harness-sdk', '--copy-metadata', 'deepseek-harness-runtime-bin',
           '--hidden-import', 'uvicorn.logging', '--hidden-import', 'uvicorn.loops.auto',
           '--hidden-import', 'uvicorn.protocols.http.auto', '--hidden-import', 'uvicorn.protocols.websockets.auto',
           '--hidden-import', 'uvicorn.lifespan.on']
for name in ('corpus', 'adjudication', 'plugins'):
    command += ['--add-data', f'{ROOT / name}:{name}']
for entry in sorted((ROOT / 'data').iterdir()):
    if entry.name != 'military-symbols-v2':
        command += ['--add-data', f'{entry}:data/{entry.name}' if entry.is_dir() else f'{entry}:data']
command += ['--add-data', f'{ROOT / "vendor/afsim/afsim-mcp"}:vendor/afsim/afsim-mcp',
            '--add-data', f'{ROOT / "vendor/afsim/afsim-skill/SKILL.md"}:vendor/afsim/afsim-skill',
            '--add-data', f'{ROOT / "vendor/afsim/afsim-skill/LICENSE.md"}:vendor/afsim/afsim-skill',
            '--add-data', f'{ROOT / "tools/afsim"}:tools/afsim']
# The upstream MCP server is loaded as source in a dedicated frozen-process
# mode; collect its standard-library imports without bundling private runtimes.
import ast
stdlib = set()
for source in (ROOT / 'vendor/afsim/afsim-mcp').rglob('*.py'):
    if 'tests' in source.parts:
        continue
    for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
        names = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) and not node.level else []
        stdlib.update(name.split('.')[0] for name in names if name.split('.')[0] in sys.stdlib_module_names)
for name in sorted(stdlib):
    command += ['--hidden-import', name]
for name in ('unit_types.json', 'korean_anchors.json', 'long_march_anchors.json', 'anti_japanese_war_anchors.json', 'missions.json', 'military_symbols.json', 'military_symbol_reference.json'):
    command += ['--add-data', f'{ROOT / "gentactix" / name}:gentactix']
command += [str(ROOT / 'tools' / 'desktop_backend.py')]
subprocess.run(command, cwd=ROOT, env=env, check=True)
if not args.backend_only:
    subprocess.run(['npm', 'run', 'dist:linux'], cwd=ROOT / 'frontend', env=env, check=True)
