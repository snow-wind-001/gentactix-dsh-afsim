#!/usr/bin/env python3
"""Project-local launch support. MCP itself remains the vendored upstream server."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[2]


def layout(project=PROJECT):
    project = Path(project).resolve()
    code = Path(getattr(sys, '_MEIPASS', project))
    vendor = project / 'vendor/afsim'
    local = vendor / 'local/afsim'
    runtime = local / 'runtime/afsim-2.9.0-win64'
    return {'project': project, 'vendor': vendor, 'local': local, 'runtime': runtime,
            'mission': runtime / 'bin/mission.exe', 'compat': local / 'compat',
            'wine': local / 'compat/usr/lib/wine/wine64',
            'prefix': local / 'wineprefix', 'state': local / 'state',
            'workspace': local / 'workspace',
            'proxy': code / 'tools/afsim/mission_proxy.py',
            'mcp': code / 'vendor/afsim/afsim-mcp/transport/stdio.py'}


def mission_command(paths, arguments, platform=None):
    platform = platform or sys.platform
    native = [str(paths['mission']), *map(str, arguments)]
    if platform == 'win32':
        return native
    if platform == 'linux':
        return [str(paths['wine']), *native]
    raise RuntimeError('此运行包仅验证 Windows 原生或 Linux/Wine 命令行方式')


def execution_env(paths, source=None, platform=None):
    env = dict(os.environ if source is None else source)
    for name in list(env):
        if name.startswith('DSH_') or name in ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'GENTACTIX_LLM_API_KEY'):
            env.pop(name)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if (platform or sys.platform) == 'linux':
        compat = paths['compat']
        lib = compat / 'usr/lib/x86_64-linux-gnu'
        env.update(WINEPREFIX=str(paths['prefix']), WINEARCH='win64', WINEDEBUG='-all',
                   WINEDLLPATH=str(lib / 'wine'),
                   LD_LIBRARY_PATH=os.pathsep.join([str(lib), str(lib / 'wine')]),
                   PATH=os.pathsep.join([str(compat / 'usr/lib/wine'), str(compat / 'usr/bin'), env.get('PATH', '')]))
    return env


def mcp_env(paths, source=None, platform=None):
    env = execution_env(paths, source, platform)
    env.update(AFSIM_ROOT=str(paths['runtime']), AFSIM_BIN=str(paths['runtime'] / 'bin'),
               AFSIM_DEMOS_DIR=str(paths['runtime'] / 'demos'),
               AFSIM_PROJECT_ROOT=str(paths['workspace']),
               AFSIM_MCP_CONFIG_DIR=str(paths['state'] / 'config'),
               AFSIM_MCP_STATE_DIR=str(paths['state'] / 'mcp'),
               AFSIM_MISSION_PATH=str(paths['mission'] if (platform or sys.platform) == 'win32' else paths['proxy']))
    return env


def status(paths=None, platform=None):
    paths = paths or layout()
    platform = platform or sys.platform
    required = [paths['mission'], paths['mcp']]
    if platform == 'linux':
        required += [paths['wine'], paths['prefix'] / 'drive_c/windows/system32/zlib1.dll']
    missing = [str(path) for path in required if not path.exists()]
    return {'available': not missing, 'verified': False, 'missing': missing,
            'mode': 'native-windows' if platform == 'win32' else 'wine-cli',
            'runtime': str(paths['runtime']),
            'note': '文件存在仅代表已配置；实际执行须检查退出码、版本和结果证据。'}


def prepare_mcp(paths=None):
    """Prepare only this project's state paths; never changes the global MCP config."""
    paths = paths or layout()
    for directory in (paths['workspace'], paths['state'] / 'config', paths['state'] / 'mcp'):
        directory.mkdir(parents=True, exist_ok=True)
    env = mcp_env(paths)
    if getattr(sys, 'frozen', False) and sys.platform == 'linux':
        import shlex
        proxy = paths['state'] / 'mission-proxy'
        proxy.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' --afsim-mission-proxy "$@"\n')
        proxy.chmod(0o700)
        env['AFSIM_MISSION_PATH'] = str(proxy)
    return env


def prepare_runtime(paths=None):
    """Recreate a project-owned Wine prefix after copying the runtime bundle."""
    paths = paths or layout()
    if sys.platform == 'win32':
        return
    import shutil
    target = paths['prefix'] / 'drive_c/windows/system32/zlib1.dll'
    if target.is_file():
        return
    env = execution_env(paths)
    env['WINEDLLOVERRIDES'] = 'mscoree,mshtml='
    subprocess.run([str(paths['wine']), 'wineboot.exe', '-u'], env=env, cwd=paths['local'], timeout=90, check=True)
    source = next((p for p in paths['compat'].rglob('zlib1.dll') if 'x86_64' in str(p)), None)
    if source is None or not target.parent.is_dir():
        raise RuntimeError('项目内Wine兼容层或zlib组件不完整')
    shutil.copy2(source, target)


def run_mission(arguments, *, paths=None, cwd=None, timeout=120):
    paths = paths or layout()
    checked = status(paths)
    if not checked['available']:
        raise RuntimeError('AFSIM 本地组件缺失：' + ', '.join(checked['missing']))
    working = Path(cwd or Path.cwd()).resolve()
    process = subprocess.Popen(mission_command(paths, arguments), cwd=working,
        env=execution_env(paths), start_new_session=sys.platform != 'win32')

    def terminate(*_args):
        if process.poll() is None:
            if sys.platform == 'win32':
                process.terminate()
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if sys.platform == 'win32':
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()

    previous = signal.signal(signal.SIGTERM, lambda *_args: (terminate(), sys.exit(143)))
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate()
        print('AFSIM 命令行运行超时；本次运行未被标记为成功。', file=sys.stderr)
        return 124
    except KeyboardInterrupt:
        terminate()
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--mcp', action='store_true')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run', type=Path)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    paths = layout(Path(os.environ.get('GENTACTIX_PROJECT_ROOT', PROJECT)))
    if args.prepare:
        prepare_runtime(paths)
        print(json.dumps(status(paths), ensure_ascii=False, indent=2))
        return 0 if status(paths)['available'] else 2
    if args.status or not (args.mcp or args.run):
        print(json.dumps(status(paths), ensure_ascii=False, indent=2))
        return 0 if status(paths)['available'] else 2
    if args.timeout <= 0 or args.timeout > 1800:
        parser.error('timeout 须为 0–1800 秒')
    if args.mcp:
        os.execve(sys.executable, [sys.executable, str(paths['mcp'])], prepare_mcp(paths))
    scenario = args.run.resolve()
    if not scenario.is_file():
        parser.error('场景文件不存在')
    return run_mission(['-es', '-sm', scenario.name], paths=paths, cwd=scenario.parent, timeout=args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())
