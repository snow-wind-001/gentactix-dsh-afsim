"""Package the host plugin and MIT references; never traverses private runtimes."""
from pathlib import Path
import argparse
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ('plugins/dsh-afsim', 'plugins/dsh-gentactix', 'tools/afsim',
         'vendor/afsim/afsim-mcp', 'vendor/afsim/afsim-skill')
FILES = ('vendor/afsim/README.md', 'vendor/afsim/dependencies.lock.json', 'LICENSE',
         'NOTICE.md', 'requirements-dsh.txt', 'requirements.txt',
         'docs/AFSIM与DSH态势分离实施规划.md', 'docs/AFSIM接入验收-2026-10-27.md',
         'backend/afsim_world.py', 'backend/afsim_state.py', 'backend/afsim_turns.py',
         'backend/afsim_comparison.py', 'backend/afsim_rules.py', 'backend/afsim_air.py',
         'backend/afsim_combined.py', 'backend/afsim_history.py', 'gentactix/combined_arms.py',
         'gentactix/history_replay.py', 'data/history_replay/curated_events.json',
         'data/long_march/scenarios.json', 'data/long_march/sources.json',
         'data/anti_japanese_war/scenarios.json', 'data/anti_japanese_war/sources.json',
         'docs/史料重现与开放推演模式.md', 'verify_history_replay.py', 'verify_combined_arms.py',
         'docs/团级多兵种统一升级方案.md', 'docs/团级多兵种与严格史料回放验收-2026-10-27.md',
         'docs/AFSIM团级装备与航空建模.md', 'docs/AFSIM功能审计与改进-2026-10-27.md',
         'verify_afsim_native.py', 'verify_afsim_air.py', 'verify_afsim_components.py',
         'verify_afsim_world.py', 'verify_afsim_backend.py')


def members():
    files = [ROOT / path for path in FILES]
    for tree in TREES:
        files.extend(path for path in (ROOT / tree).rglob('*') if path.is_file()
                     and not any(part in ('__pycache__', '.git', '.pytest_cache') for part in path.parts)
                     and path.suffix not in ('.pyc', '.pyo'))
    return sorted(set(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'release/afsim/gentactix-dsh-afsim-0.1.0.zip')
    args = parser.parse_args(); target = args.out.resolve(); target.parent.mkdir(parents=True, exist_ok=True)
    paths = members()
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr('bundle.json', json.dumps({'name': 'gentactix-dsh-afsim', 'version': '0.1.0',
            'host': 'requires matching GenTactix source/backend; not a standalone simulator',
            'private_runtime_included': False, 'dependencies': 'vendor/afsim/dependencies.lock.json',
            'files': [path.relative_to(ROOT).as_posix() for path in paths]}, ensure_ascii=False, indent=2))
    print(f'{target}: {len(paths)} files, {target.stat().st_size} bytes; private runtime excluded')


if __name__ == '__main__':
    main()
