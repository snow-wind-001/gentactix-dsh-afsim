"""Compare the same explicit four-hour QA inputs with 30-minute native steps."""
import argparse
import copy
import json
from pathlib import Path
import urllib.request
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    if not p.parse_args().live:p.error('Use --live against the isolated QA service')
    from gentactix import missions
    root=Path('.cache/qa/selected-step')
    def call(method,path,value=None):
        request=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,
            headers={'Content-Type':'application/json'},data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        with urllib.request.urlopen(request,timeout=1200) as r:return json.load(r)
    def save(name,v):(root/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2))
    assert not call('GET','/api/health')['build']['restart_required']
    original=json.loads((root/'initial.json').read_text())
    parent_id='9a4a14968eac4119b5f146f403ecba70'
    parent=json.loads((root.parent/'ww2-phases/runtime/scenario-drafts'/(parent_id+'.json')).read_text())
    frozen=parent['parameters']
    config=copy.deepcopy(frozen);config['clock']['time_step']='30分钟';config['goal']['deadline_turn']=8
    draft=call('POST','/api/historical-scenarios/validate',{'parameters':config,
        'parent_draft_id':parent_id,'execution_backend':'afsim'})
    save('partition-draft',draft)
    sid=call('POST','/api/sessions',{'scenario':'相同具名初态四小时步长比较；数值为原QA估计，非史实实到',
        'battle':draft['initial']['definition']['battle'],'product_mode':'historical','execution_backend':'afsim',
        'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id'],'time_step':'30分钟','use_rag':True,'persist_roles':False})['session_id']
    initial=call('POST',f'/api/sessions/{sid}/init');save('partition-initial',initial)
    assert initial['war_state']['red_units']==original['war_state']['red_units']
    assert initial['war_state']['blue_units']==original['war_state']['blue_units']
    for turn in range(1,9):
        view=call('GET',f'/api/sessions/{sid}/commands')
        revision={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')}}
        targets={team:next(u for u in view['units'] if u['team']==team)['id'] for team in ('red','blue')}
        orders=[{'unit_id':u['id'],'duration':'next',**({'action':'fire','target_id':targets['blue' if u['team']=='red' else 'red']}
            if 'fire' in u['capabilities']['actions'] else {'action':'hold'})} for u in view['units']]
        call('PUT',f'/api/sessions/{sid}/commands',{**revision,'orders':orders,'control_team':'red','director':True,'no_fire':False,'unit_agents':[]})
        view=call('GET',f'/api/sessions/{sid}/commands');revision={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')}}
        after=call('POST',f'/api/sessions/{sid}/next',{**revision,'batch_id':uuid.uuid4().hex})
        missions.validate(after['war_state']);save('partition-turn'+str(turn),after)
        assert after['war_state']['simulation_clock']['elapsed_seconds']==turn*1800
        print('PASS partition turn',turn,flush=True)
    assert after['war_state']['current_time']=='1938-03-24 12:00'
    assert after['war_state']['mission']['status']!='active'
    final=json.loads((root/'final.json').read_text())
    rows=[]
    for team in ('red','blue'):
        small=final['war_state'][team+'_units'][0];large=after['war_state'][team+'_units'][0]
        rows.append({'name':small['name'],'15_min':small['personnel'],'30_min':large['personnel'],
            'casualty_relative_difference':abs(large['personnel']['casualties']-small['personnel']['casualties'])/max(1,small['personnel']['casualties']),
            'ammo_15':small['logistics']['ammo'],'ammo_30':large['logistics']['ammo']})
    save('partition-result',{'passed_clock_and_accounting':True,'session_id':sid,'only_input_changes':['clock.time_step','goal.deadline_turn','program_generated_goal_description'],
        'historical_fit_verified':False,'rows':rows,'scope':'Orders are reissued at different intervals; outcome differences require interpretation, not historical-rate calibration.'})
    print('PASS same initial actors; both four-hour clocks and conserved ledgers',flush=True)


if __name__=='__main__':main()
