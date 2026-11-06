"""Read-only actual DSH observation of native partition accounts."""
import argparse
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
if not parser.parse_args().live:
    parser.error('Use --live against owned isolated API18998')
root = Path('.cache/qa/formation-partitions')
sid = json.loads((root / 'session-ids.json').read_text())['afsim']
base = 'http://127.0.0.1:18998/api/sessions/' + sid
home = Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions')
offsets = {str(path): path.stat().st_size for path in home.glob('*/*/session.v4.jsonl')}


def call(path='', value=None):
    req = urllib.request.Request(base + path, headers={'Content-Type': 'application/json'},
        data=None if value is None else json.dumps(value, ensure_ascii=False).encode())
    with urllib.request.urlopen(req, timeout=1200) as response:
        return json.load(response)


def save(name, value):
    (root / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


before = call()['war_state']
save('review-before', before)
answer = call('/chat', {'message': '只读核对本局：请实际读取原生态势工具，用简短表格列出军委纵队各计算分队的人数、位置、最后动作与当前粮弹，并给父单位汇总人数及粮弹。说明这些数值的单位和来源，当前计算分队是否等于史实编制；不能把归一化粮弹覆盖值简单相加。不要下命令、改变主局、试算或引用旧对话代替本轮观测。'})
save('review', answer)
assert answer['engine_meta']['finish_reason'] == 'completed'
assert answer['war_state'] == before and call()['war_state'] == before
calls = []
for path in home.glob('*/*/session.v4.jsonl'):
    offset = offsets.get(str(path), 0)
    if path.stat().st_size == offset:
        continue
    with path.open('rb') as stream:
        stream.seek(offset)
        for line in stream:
            if not line.endswith(b'\n'):
                continue
            row = json.loads(line)
            if row.get('type') == 'tool/call':
                calls.append({'session_id': path.parent.name, 'seq': row.get('seq'), **(row.get('data') or {})})
save('review-tools', calls)
assert any(row['name'] == 'get_afsim_observation' for row in calls)
save('review-results', {'readonly': True, 'actual_native_observation': True, 'free_text_needs_review': True})
print('PASS actual native tool observation, unchanged committed world; review public answer separately', flush=True)
