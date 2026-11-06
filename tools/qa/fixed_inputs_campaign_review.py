"""Check22fixed campaign inputs across real Native unit scopes and initial load."""
import json
from pathlib import Path


def main():
    root=Path('.cache/qa/fixed-parameters-2026-11-01')
    data=json.loads((root/'campaign-build.json').read_text());body=data['body']
    assert data['http']==200
    rows=data['request']['fixed_parameters'];assert len(rows)==22
    assert body['construction']['fixed_parameters']['values']==rows
    expected={r['path'][1]:r['value'] for r in rows}
    assert set(expected)==set(body['parameters']['actors'])
    assert all(a['personnel']==expected[i] for i,a in body['parameters']['actors'].items())
    stages=body['construction']['stages']
    assert [s['part'] for s in stages]==['globals',*[f'actors:{i}' for i in range(6)],'final']
    session_ids={s['session_id'] for s in stages};views=[];seen=set();updates=[]
    for path in (root/'browser').glob('dsh-home/sessions/**/session.v4.jsonl'):
        if path.parent.name not in session_ids:continue
        for line in path.read_text().splitlines():
            event=json.loads(line)
            if event['type']!='tool/result':continue
            for block in event['data']['message'].get('content',[]):
                if block.get('type')!='text':continue
                try:d=json.loads(block['text'])
                except (ValueError,TypeError):continue
                if not isinstance(d,dict):continue
                if 'updated' in d:updates.append({'updated':d['updated'],'revision':d['revision'],'error':d.get('error')})
                if d.get('workflow')!='staged_historical_configuration':continue
                assert 'fixed_parameter_fields' not in d
                visible=d['fixed_parameters']['values'];assigned=set(d['assigned_actor_ids'])
                assert d['fixed_parameters']['total']==22
                assert all(r['path'][0]=='actors' and r['path'][1] in assigned for r in visible)
                if d['part'].startswith('actors:'):
                    assert {r['path'][1] for r in visible}==assigned
                    assert len(assigned)<=4
                    seen.update(assigned)
                else:assert not visible
                views.append({'part':d['part'],'assigned':sorted(assigned),'visible_fixed_values':len(visible)})
    assert seen==set(expected)
    assert sum(r['updated'] for r in updates)>=7
    assert body['afsim']['entity_count']==22 and body['afsim']['returncode']==0
    assert body['preview_world']['mission']['turn']==body['preview_world']['simulation_clock']['elapsed_seconds']==0
    result={'passed':True,'actual_model':True,'actual_frontend':True,'actual_afsim_load':True,'actors':22,
            'fixed_fields':22,'fixed_numeric_mismatches':0,'stages':len(stages),'unit_shards':6,
            'all_shards_observed_only_assigned_fixed_inputs':True,'native_updates':updates,'native_views':views,
            'meta':body['construction']['meta'],
            'scope':'Wanjialing optional1.3 model priors and8Native stages; not historical strengths or full5day battle acceptance'}
    (root/'campaign-native-review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('meta','native_updates','native_views')},ensure_ascii=False))


if __name__=='__main__':main()
