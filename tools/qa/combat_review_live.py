"""Real native bilateral fire and scoped loss-review acceptance, not historical fit."""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from tools.qa.historical_operational_fixture import BATTLE, inputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--port',type=int,default=18996)
    parser.add_argument('--out',type=Path,default=Path('.cache/qa/combat-review'))
    args=parser.parse_args()
    if not args.live or not 18900<=args.port<=18999:raise SystemExit('Use --live and an isolated QA port')
    base=f'http://127.0.0.1:{args.port}';root=args.out;root.mkdir(parents=True,exist_ok=True)
    result={'passed':False,'checks':[],'scope':'Actual AFSIM and native DSH plugin; explicit QA strengths and positions, not historical casualty calibration'}

    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))

    def call(method,path,data=None):
        req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as response:return json.load(response)
        except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:1600]) from exc

    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)

    def create(label,ammo=80):
        _,p=inputs();p=copy.deepcopy(p);p['goal']['deadline_turn']=30
        for actor in p['actors'].values():actor['logistics']['ammo']=ammo
        sid=call('POST','/api/sessions',{'scenario':label+'；数值与局部部署是QA假设，不宣称历史拟合',
            'battle':BATTLE,'product_mode':'historical','execution_backend':'afsim','historical_parameters':p,'persist_roles':False})['session_id']
        snap=call('POST',f'/api/sessions/{sid}/init');save(label+'-initial',snap)
        return sid,snap

    def advance(label,sid,fire=True):
        path=f'/api/sessions/{sid}';view=call('GET',path+'/commands')
        red=next(u for u in view['units'] if u['team']=='red');blue=next(u for u in view['units'] if u['name']=='日军濑谷支队')
        fighters={red['id']:blue['id'],blue['id']:red['id']}
        orders=[{'unit_id':u['id'],'action':'fire' if fire and u['id'] in fighters else 'hold','duration':'next',
            **({'target_id':fighters[u['id']]} if fire and u['id'] in fighters else {})} for u in view['units']]
        revision={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')}}
        view=call('PUT',path+'/commands',{**revision,'orders':orders,'control_team':'red','director':True,
            'no_fire':False,'unit_agents':[],'intent':'双方持续交火与战损时长核查'})
        revision={'expected_turn':view['turn'],**{k:view[k] for k in ('revision','world_version')},'batch_id':uuid.uuid4().hex}
        snap=call('POST',path+'/next',revision);save(label+f'-turn{snap["turn_count"]}',snap)
        return snap

    try:
        check(not call('GET','/api/health')['build']['restart_required'],'current source backend')
        sid,initial=create('bilateral');result['session_id']=sid
        for turn in range(1,7):
            snap=advance('bilateral',sid);world=snap['war_state']
            check(world['historical_initial']==initial['war_state']['historical_initial'],f'turn{turn} historical identity unchanged')
            check(world['afsim']['model_skipped'] and world['afsim']['source']=='dsh_native_mcp_controller',f'turn{turn} real native execution with explicit bilateral commands')
            for side in ('red','blue'):
                for u in world[side+'_units']:
                    p=u['personnel']
                    assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
                    assert p['casualties']==sum(p[k] for k in ('killed','wounded','missing','captured','unclassified_casualties'))
        rows={r['name']:r for r in world['combat_assessment']['units']}
        units={u['name']:u for side in ('red','blue') for u in world[side+'_units']}
        check(world['simulation_clock']['elapsed_seconds']==10800,'three authoritative hours')
        for name in ('第31师','日军濑谷支队'):
            check(units[name]['personnel']['casualties']>20 and units[name]['personnel']['killed']>5,name+' sustained bilateral fire does not yield a few total losses')
            check(rows[name]['tracked_incoming_max_fire_s']>=7200,name+' at least two hours of native incoming fire receipts')
        check(rows['日军坂本支队']['tracked_incoming_max_fire_s']==0 and units['日军坂本支队']['personnel']['casualties']==0,'untargeted reserve has no quota losses')
        check(rows['第31师']['historical_reference']['casualties_approx']==3000 and not world['combat_assessment']['historical_fit_verified'],'same-unit historical reference present without false fit claim')
        low,low_initial=create('limited',3);limited=advance('limited',low)
        for u in limited['war_state']['red_units']+limited['war_state']['blue_units']:
            if u['name']=='日军坂本支队':continue
            r=u['formation']['last_execution']
            check(r['fire_cycles']==3 and r['fire_stop_reason']==8,u['name']+' stops at actual ammo budget')
        check(all(r['incoming_max_fire_s']<600 for r in limited['war_state']['combat_assessment']['units']),'half-hour elapsed is not reported as half-hour fire after ammunition exhaustion')
        quiet,quiet_initial=create('quiet');quiet_snap=advance('quiet',quiet,False)
        check(all(u['personnel']['casualties']==0 for side in ('red','blue') for u in quiet_snap['war_state'][side+'_units']),'no combat means no fabricated historical losses')
        result.update(passed=True,totals={name:{k:u['personnel'][k] for k in ('committed','current','casualties','killed','wounded')} for name,u in units.items()},
            limited_session=low,quiet_session=quiet)
        save('result',result)
        print(json.dumps({'passed':True,'session_id':sid,'totals':result['totals']},ensure_ascii=False),flush=True)
    except Exception as exc:
        result['error']=str(exc);save('result',result);raise


if __name__=='__main__':main()
