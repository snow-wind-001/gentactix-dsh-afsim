"""Read-only real DSH observation of native ferry state and committed changes."""
import argparse
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true')
parser.add_argument('--weighted', action='store_true')
args = parser.parse_args()
if not args.live:
    parser.error('Owned isolated API18998 and actual DSH access require --live')
root = Path('.cache/qa/ferry-model')
sid = json.loads((root / 'session-ids.json').read_text())['afsim']
base = 'http://127.0.0.1:18998/api/sessions/' + sid
home = Path('.cache/qa/ww2-phases/runtime/dsh-home/sessions')
offsets = {str(path): path.stat().st_size for path in home.glob('*/*/session.v4.jsonl')}


def call(path='', value=None):
    request = urllib.request.Request(base + path, headers={'Content-Type': 'application/json'},
        data=None if value is None else json.dumps(value, ensure_ascii=False).encode())
    with urllib.request.urlopen(request, timeout=1200) as response:
        return json.load(response)


def save(name, value):
    prefix = 'weighted-' if args.weighted else ''
    (root / (prefix + name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


before = call()['war_state']
save('review-before', before)
question = (
    '只读核对本局，请实际调用get_afsim_observation和get_afsim_changes，'
    '说明当前每艘船的位置、阶段、乘载分队及人数、完成登岸航次，'
    '并核对这支分队与未登船主队合计人数。区分登船、河中航行和完成登岸；'
    '说明这些数据是AFSIM原生计算还是历史记载，是否真的重现1935年先遣队。'
    '只回答本次已提交态势，不试算、不下命令、不改主局，不能用旧对话代替观察。')
if args.weighted:
    question = ('只读复核，请实际调用get_afsim_observation和get_afsim_changes。'
        '用简短计算核对五人分队本轮food覆盖变化与food_spent之间是否存在未解释差额，'
        '明确scale及计量单位；再给主队和分队合计人数、父组food覆盖、舟艇载员及完成航次。'
        '只依据已提交的本轮观察，区分模型估计与史实；不下命令、不试算、不改主局。')
answer = call('/chat', {'message': question})
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
            if line.endswith(b'\n'):
                row = json.loads(line)
                if row.get('type') == 'tool/call':
                    calls.append({'session_id': path.parent.name, 'seq': row.get('seq'), **(row.get('data') or {})})
save('review-tools', calls)
assert {'get_afsim_observation', 'get_afsim_changes'} <= {row['name'] for row in calls}
save('review-results', {'passed': True, 'readonly': True, 'actual_native_tools': True,
                        'public_answer_requires_numeric_review': True})
print('PASS real native observation and changes; committed world unchanged; inspect public answer', flush=True)
