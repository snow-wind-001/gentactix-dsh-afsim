"""Actual API validation of shared process inputs and DSH-estimated receipts."""
import argparse
import copy
import json
from pathlib import Path
import time

from tools.qa.catalog_expansion_live import call,fire_orders,revision,advance


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live against owned isolated API18998')
    root=Path('.cache/qa/fire-process/live');root.mkdir(parents=True,exist_ok=True)
    health=call('GET','/api/health');assert not health['build']['restart_required']
    assert Path(f"/proc/{health['build']['pid']}/cmdline").read_bytes().split(b'\0')[1]==b'.cache/qa/ww2-phases/launch.py'
    draft=json.loads(Path('.cache/qa/catalog-expansion/actual-builder-draft.json').read_text())
    result={'passed':False,'scope':'same frozen UI-generated QA inputs, not historical calibration','cases':[]}
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    def turn(sid,case):
        view=call('GET','/api/sessions/'+sid+'/commands')
        call('PUT','/api/sessions/'+sid+'/commands',{**revision(view),'orders':fire_orders(view),
            'director':True,'control_team':'red','no_fire':False,'unit_agents':[],
            'intent':'QA双方确认fire命令，依据冻结参数、有效时段和资源执行，不预设任何伤亡数。'})
        print('START',case,sid,flush=True);start=time.monotonic()
        response=advance(sid,'双方执行已确认的fire命令，按本局冻结的火力过程先验、联络等待、装填和反馈逐段估计。'
            '必须覆盖双方并提交本轮协议；不要按历史损失或上一轮固定损失扣人。没有实际发射则不写交火和伤亡。'
            '不改变事实、规则或已确认命令；AFSIM关闭时过程结果及回执均为DSH估计，不能声称原生遥测。')
        save(case,response);world=response['war_state']
        rows=[{'unit':u['name'],'casualties':u['personnel']['casualties'],
               'suppression':u['formation']['suppression'],'intel_age_min':u['formation']['intel_age_min'],
               'ammo':u['logistics']['ammo']} for t in ('red','blue') for u in world[t+'_units']]
        item={'case':case,'session_id':sid,'seconds':round(time.monotonic()-start,3),'units':rows}
        if world.get('dsh_execution'):
            ledger=world['dsh_execution']['fire_ledger']
            assert ledger['source']=='dsh_model_estimate' and ledger['turn']==response['turn_count']
            assert len(ledger['units'])==2
            item['fire_ledger']=ledger
        result['cases'].append(item);save('result',result);print('PASS',case,item['seconds'],[(u['casualties'],u['ammo']) for u in rows],flush=True)
        return response
    try:
        for step,seconds in [('15分钟',900),('1分钟',60)]:
            starts=[]
            for engine in ['afsim','narrative']:
                params=copy.deepcopy(draft['parameters']);params['clock']['time_step']=step
                params['clock']['assumption']+='；本次QA改用'+step+'，不更改其他初态。'
                created=call('POST','/api/sessions',{'scenario':'共享火力过程QA；显式估计参数、非史实实力或战损',
                    'battle':draft['initial']['definition']['battle'],'historical_parameters':params,
                    'product_mode':'historical','simulation_mode':'open','execution_backend':engine,
                    'persist_roles':False,'time_step':step})
                sid=created['session_id'];save(engine+'-'+str(seconds)+'-session',created)
                first=call('POST','/api/sessions/'+sid+'/init');save(engine+'-'+str(seconds)+'-initial',first)
                starts.append(first['war_state']['historical_initial'])
                response=turn(sid,engine+'-'+str(seconds)+'-turn1');w=response['war_state']
                assert w['historical_initial']==first['war_state']['historical_initial']
                assert w['simulation_clock']['elapsed_seconds']==seconds
                for team in ['red','blue']:
                    for u in w[team+'_units']:
                        p=u['personnel'];assert p['committed']==sum(p[k] for k in ['current','casualties','noncombat_losses'])
                if seconds==60:
                    assert not w['engagements']
                    assert all(u['personnel']['casualties']==0 for t in ['red','blue'] for u in w[t+'_units'])
                    if engine=='narrative':assert all(r['fire_cycles']==0 and r['first_fire_s'] is None for r in w['dsh_execution']['fire_ledger']['units'])
                elif engine=='narrative':
                    assert all(0<r['fire_cycles']<=7 for r in w['dsh_execution']['fire_ledger']['units'])
                    following=turn(sid,'narrative-900-turn2')
                    assert following['war_state']['simulation_clock']['elapsed_seconds']==1800
                    assert following['war_state']['historical_initial']==first['war_state']['historical_initial']
            assert starts[0]==starts[1]
        result['passed']=True;save('result',result)
    except Exception as exc:
        result['error']=str(exc);save('result',result);raise


if __name__=='__main__':main()
