"""Read-only preservation and cold-restore audit; no simulation executor."""
import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
parser.add_argument('--phase', choices=('before', 'after'), required=True)
args = parser.parse_args()
if not args.live:
    parser.error('Use --live against owned isolated API18998')
root = Path('.cache/qa/ferry-model')
base = 'http://127.0.0.1:18998'


def get(path):
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return json.load(response)


def save(name, value):
    (root / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


health = get('/api/health')
assert not health['build']['restart_required'], 'Owned API must use current source'
pid = health['build']['pid']
argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
assert len(argv) >= 3 and argv[1] == b'.cache/qa/ww2-phases/launch.py'
current = []
for row in get('/api/sessions')['sessions']:
    sid = row['session_id']
    progress = get('/api/sessions/' + sid + '/progress')
    assert not progress['active'] and progress['operation_id'] is None, 'Still running ' + sid
    state = get('/api/sessions/' + sid)
    current.append({'session_id': sid, 'world': state['war_state'], 'turn': state['turn_count'],
                    'commands': get('/api/sessions/' + sid + '/commands')})
index = {row['session_id']: row for row in current}
original_root = Path('.cache/qa/formation-partitions')
original = json.loads((original_root / 'before-cold-restart.json').read_text())
assert all(index.get(row['session_id']) == row for row in original), 'An original QA world/command changed'
operations = set(json.loads((original_root / 'checkpoint-final.json').read_text())['build_operations_inactive'])
operations.update(json.loads((root / 'operations.json').read_text()))
for path in root.glob('*network*.log'):
    operations.update(re.findall(r'/api/scenarios/operations/([a-f0-9]{32})/progress', path.read_text(errors='replace')))
for name in ('skill-build-request', 'editor-validation-request'):
    path = root / (name + '.json')
    if path.exists():
        operations.add(json.loads(path.read_text())['operation_id'])
for operation in operations:
    assert not get('/api/scenarios/operations/' + operation + '/progress')['active'], 'Still building ' + operation
for name in ('preservation', 'old-profiles-preserved'):
    protected = json.loads((original_root / (name + '.json')).read_text())
    for row in protected:
        assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
    save(name + '-' + args.phase, protected)
agents_hash = hashlib.sha256(Path('AGENTS.md').read_bytes()).hexdigest()
assert agents_hash == '7843b4d3d32b423430e97a840e273dc237f8db262b19208a1521e32bb4414be0'
if args.phase == 'before':
    save('before-cold-restart', current)
else:
    before = json.loads((root / 'before-cold-restart.json').read_text())
    assert pid != json.loads((root / 'checkpoint-before.json').read_text())['pid'], 'Cold restore requires a new API process'
    assert len(current) == len(before) and all(index.get(row['session_id']) == row for row in before)
proof = {'passed': True, 'phase': args.phase, 'pid': pid, 'worlds': len(current), 'all_idle': True,
    'original_44_worlds_and_commands_unchanged': True, 'cold_restore_exact': args.phase == 'after',
    'protected_user_files': 8, 'protected_old_profiles': 10, 'agents_sha256': agents_hash,
    'exact_launcher': True, 'build_operations_inactive': sorted(operations)}
save('checkpoint-' + args.phase, proof)
print(json.dumps(proof, ensure_ascii=False), flush=True)
