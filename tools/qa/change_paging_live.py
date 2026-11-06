"""Opt-in 24-unit native change paging and read-only DSH audit; not history QA."""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    p.add_argument('--port', type=int, default=18998)
    p.add_argument('--out', type=Path, default=Path('.cache/qa/change-paging'))
    a = p.parse_args()
    if not a.live or not 18900 <= a.port <= 18999:
        p.error('Use --live with an isolated QA service')
    from gentactix import combined_arms
    root = a.out; root.mkdir(parents=True, exist_ok=True)
    result = {'passed': False, 'checks': [], 'historical_fit_verified': False}
    def save(name, value):
        (root/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    def check(ok, label):
        if not ok:
            raise AssertionError(label)
        result['checks'].append(label); print('PASS', label, flush=True)
    def call(method, path, value=None):
        req = urllib.request.Request(f'http://127.0.0.1:{a.port}'+path, method=method,
            headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value, ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req, timeout=1200) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:1500]) from exc
    def revision(view):
        return {'expected_turn':view['turn'], **{k:view[k] for k in ('revision','world_version')}}
    started = time.monotonic()
    try:
        check(not call('GET','/api/health')['build']['restart_required'], 'fresh source API')
        cfg = combined_arms.configuration('CA-AJ18-v1')
        for team in ('red','blue'):
            base = copy.deepcopy(cfg['teams'][team][0]); rows = []
            for i in range(12):
                row = copy.deepcopy(base)
                row.update(name=f'{team}-paging-{i+1:02d}', personnel=1000, shells=0, aa_rounds=0)
                row['equipment'] = {k:0 for k in row['equipment']}
                rows.append(row)
            cfg['teams'][team] = rows
        sid = call('POST','/api/sessions',{'scenario':'24单位分页软件压力测试，全合成，不是历史战役验收。',
            'mission_id':'CA-AJ18-v1','execution_backend':'afsim','synthetic_configuration':cfg,
            'persist_roles':False})['session_id']
        result['session_id'] = sid
        initial = call('POST',f'/api/sessions/{sid}/init'); save('initial',initial)
        check(initial['war_state']['afsim']['entity_count']==24, 'actual native world contains all 24 synthetic actors')
        v = call('GET',f'/api/sessions/{sid}/commands')
        call('PUT',f'/api/sessions/{sid}/commands',{**revision(v),
            'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in v['units']],
            'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
        v = call('GET',f'/api/sessions/{sid}/commands')
        after = call('POST',f'/api/sessions/{sid}/next',{**revision(v),'batch_id':uuid.uuid4().hex})
        save('turn',after); before = copy.deepcopy(after['war_state'])
        check(after['war_state']['afsim']['entity_count']==24, 'native turn preserves 24 actors')
        check(all(u['personnel']['current']==1000 for t in ('red','blue') for u in before[t+'_units']),
              'holding formations do not receive an invented casualty quota')
        exported = call('GET',f'/api/sessions/{sid}/export')['session']
        changes = exported['trajectory'][-1]['changes']
        check(len(changes)==24, 'actual committed trajectory contains 24 unit changes')
        response = call('POST',f'/api/sessions/{sid}/chat',{'message':
            '这次只验收get_afsim_changes的完整分页。先调用limit=16,since_turn=0,through_turn=1,offset=0；'
            '然后严格沿next_args读取剩余页面，直到next_args为空。不要只读第一页。'
            '最终列出实际读到的全部单位名称，说明每页条数与总数、是否出现减员。缺载字段保持未知，不下命令不改战局。'})
        save('analysis',response)
        check(response['war_state']==before, 'real DSH reads all changes without changing the world')
        check(response['engine_meta']['finish_reason']=='completed', 'real native DSH analysis completed')
        headers, calls = [], []
        for path in (root/'runtime/dsh-home/sessions').rglob('session.v4.jsonl'):
            for line in path.open():
                event = json.loads(line)
                if event.get('type')=='request/header':
                    h = event['data']['header']; c = h['config']
                    headers.append({'tools':[t['name'] for t in h.get('tools',[])],
                        'reasoning_effort':c.get('reasoningEffort'),'max_tokens':c.get('maxTokens')})
                if event.get('type')=='tool/call':
                    d = event.get('data',{}); calls.append(d)
        save('native-headers',headers); save('native-tool-calls',calls)
        paging = [c for c in calls if c.get('name')=='get_afsim_changes']
        parsed = [json.loads(c['arguments']) if isinstance(c.get('arguments'),str) else c.get('arguments',{}) for c in paging]
        check(any(c.get('offset')==16 and c.get('view_version') for c in parsed),
              'actual native tool call follows version-pinned next_args to offset 16')
        check(headers and all(h['reasoning_effort']=='high' and h['max_tokens']==65536 for h in headers),
              'isolated QA retains high reasoning and 64K output')
        text = response['chat_messages'][-1]['content']
        check(all(u['name'] in text for t in ('red','blue') for u in before[t+'_units']),
              'answer includes every actual unit, including the last page')
        result.update(passed=True,units=24,seconds=round(time.monotonic()-started,2))
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        save('result',result)


if __name__=='__main__':
    main()
