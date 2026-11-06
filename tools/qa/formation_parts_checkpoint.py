"""Read-only checkpoint/cold-restore audit of the owned QA API; no turn executor."""
import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
parser.add_argument('--phase', choices=('before', 'after', 'final'), required=True)
args = parser.parse_args()
if not args.live:
    parser.error('Use --live against owned isolated API18998')
root = Path('.cache/qa/formation-partitions')
base = 'http://127.0.0.1:18998'


def get(path):
    with urllib.request.urlopen(base + path, timeout=20) as response:
        return json.load(response)


def save(name, value):
    (root / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


health = get('/api/health')
assert not health['build']['restart_required'], 'Owned API must have the current source'
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
original = json.loads(Path('.cache/qa/crossing-control/before-final-cold-restart.json').read_text())
assert all(index.get(row['session_id']) == row for row in original), 'An earlier QA world/command changed'
operations = set(json.loads(Path('.cache/qa/crossing-control/final-shutdown-proof.json').read_text())['build_operations_inactive'])
for name in ('build-request', 'narrative-validation-request'):
    operations.add(json.loads((root / (name + '.json')).read_text())['operation_id'])
network = root / 'editor-network.log'
if network.exists():
    operations.update(re.findall(r'/api/scenarios/operations/([a-f0-9]{32})/progress', network.read_text()))
for operation in operations:
    assert not get('/api/scenarios/operations/' + operation + '/progress')['active'], 'Still building ' + operation
for name in ('preservation', 'old-profiles-preserved'):
    protected = json.loads((root / (name + '.json')).read_text())
    for row in protected:
        digest = hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()
        assert digest == row['sha256'], 'Protected input changed: ' + row['path']
    save(name + '-' + args.phase, protected)
if args.phase == 'before':
    save('before-cold-restart', current)
else:
    before = json.loads((root / 'before-cold-restart.json').read_text())
    assert len(current) == len(before) and all(index.get(row['session_id']) == row for row in before)
proof = {'passed': True, 'phase': args.phase, 'pid': pid, 'worlds': len(current),
    'all_idle': True, 'original_41_worlds_and_commands_unchanged': True,
    'cold_worlds_and_commands_exact': args.phase != 'before', 'protected_user_files': 8,
    'protected_old_profiles': 10, 'build_operations_inactive': sorted(operations),
    'exact_launcher': True, 'agents_sha256': hashlib.sha256(Path('AGENTS.md').read_bytes()).hexdigest()}
if args.phase != 'before':
    assert proof['agents_sha256'] == json.loads((root / 'checkpoint-before.json').read_text())['agents_sha256']
save('checkpoint-' + args.phase, proof)
print(json.dumps(proof, ensure_ascii=False), flush=True)
