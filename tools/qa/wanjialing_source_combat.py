"""Verify actual contact and one same-state decision contrast, no history quota."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import uuid


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--port',type=int,default=19097)
    args=p.parse_args()
    if not args.live or not 19090<=args.port<=19110:p.error('Use --live with isolated QA backend')
    root=Path('.cache/qa/wanjialing-sources-2026-10-31/build');original=json.loads((root/'result.json').read_text())
    sid=original['session_id'];base=f'http://127.0.0.1:{args.port}/api/sessions/{sid}'
    def call(method,path,body=None):
        req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req,timeout=1200) as r:return json.load(r)
        except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:2000]) from e
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def revision(v):return {'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    result={'passed':False,'session_id':sid,'scope':'Real generated partial-force parameters, not historical casualty calibration'}
    try:
        initial=call('GET','');assert initial['turn_count']==1,'This test starts at verified turn one'
        v=call('GET','/commands');by_name={u['name']:u for u in v['units']};red=by_name['第159师'];blue=by_name['日军第106师团']
        assert red['capabilities']['arrival']['status']=='active' and blue['capabilities']['arrival']['status']=='active'
        assert 'fire' in red['capabilities']['actions'] and 'fire' in blue['capabilities']['actions']
        orders=[{'unit_id':u['id'],'action':'fire' if u['id'] in (red['id'],blue['id']) else 'hold',
            **({'target_id':blue['id'] if u['id']==red['id'] else red['id']} if u['id'] in (red['id'],blue['id']) else {}),
            'duration':'next'} for u in v['units']]
        call('PUT','/commands',{**revision(v),'orders':orders,'control_team':'red','director':True,'no_fire':False,'intent':'已到场159师与106师团交战；未到场部队明确等待'})
        v=call('GET','/commands');snap=call('POST','/next',{**revision(v),'batch_id':uuid.uuid4().hex});save('manual-turn2',snap)
        world=snap['war_state'];assert world['current_time']=='1938-10-07 01:00'
        losses={team:sum(u['personnel']['casualties'] for u in world[team+'_units']) for team in ('red','blue')}
        assert losses['red']>0 and losses['blue']>0,losses
        for u in world['red_units']+world['blue_units']:
            a=u['personnel'];assert a['committed']==a['current']+a['casualties']+a['noncombat_losses']
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        v=call('GET','/commands');branch=call('POST','/commands/compare',{**revision(v),'turn':2,
            'orders':[{'unit_id':red['id'],'action':'hold','duration':'next'}]});save('manual-branch',branch)
        alternative=sum(u['personnel']['casualties'] for u in branch['alternative']['blue_units'])
        assert alternative<losses['blue'],(alternative,losses)
        assert call('GET','')['war_state']==world,'Counterfactual must not mutate main world'
        result.update(passed=True,losses=losses,alternative_blue_losses=alternative,model_skipped=snap['afsim']['model_skipped'],time=world['current_time'])
        print('PASS actual contact after staged arrival, mutual casualties, exact ledgers and same-state hold intervention',flush=True)
    finally:save('combat-result',result);print('Evidence:',root,flush=True)


if __name__=='__main__':main()
