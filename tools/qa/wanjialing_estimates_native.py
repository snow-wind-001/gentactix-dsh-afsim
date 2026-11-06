"""Real native fire and 6/48/96-hour stock contrasts under explicit priors.

No model call, source-event forcing, Python combat or historical calibration.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--resume-stocks',type=Path,help='Continue retained96-hour contrasts; do not rerun them')
    args=parser.parse_args()
    if not args.live:parser.error('--live required for actual AFSIM')
    root=Path('.cache/qa/wanjialing-estimates-2026-11-01/native')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),
                       ('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str((root/suffix).resolve())
    from gentactix import historical_operations as ho,missions,sim_clock
    from backend import afsim_world,afsim_rules,harness_engine
    from tools.qa.wanjialing_estimate_fixture import inputs
    result=dict(passed=False,actual_afsim=True,actual_model=False,cases=[],
        scope='Exploratory22-actor native process contrasts, not a complete historical campaign or calibrated ration model')
    def save():(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def run(label,before,orders):
        seconds=sim_clock.duration_seconds(before['mission']['definition']['time_step']);prior=copy.deepcopy(before)
        scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('Native physical executor required')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,before['mission']['definition']['time_step'])
        missions.evaluate(after)
        missions.validate(after);assert before==prior
        units=list(missions.units(after));assert len(units)==22
        for _,u in units:
            p=u['personnel'];assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False)+'\n')
        core=next(u for _,u in units if u['historical_unit_id']=='ww2.jp.division106')
        row=dict(label=label,turn=after['mission']['turn'],time=after['current_time'],engagements=len(after.get('engagements',[])),
            casualties={t:sum(u['personnel']['casualties'] for u in after[t+'_units']) for t in ('red','blue')},
            core_food=core['logistics']['food'],core_shortage_hours=core['sustainment']['shortage_hours'],
            core_noncombat=core['personnel']['noncombat_losses'],goal_resolution=after['campaign_plan']['resolution'],native=evidence)
        result['cases'].append(row);save();print('PASS',label,flush=True);return after
    try:
        if args.resume_stocks:
            moves={};states={v:json.loads((args.resume_stocks/(v+'-96h.json')).read_text()) for v in ('supplied','stock_zero')}
            cores={v:next(u for _,u in missions.units(w) if u['historical_unit_id']=='ww2.jp.division106') for v,w in states.items()}
            budget=min(missions.move_budget(states[v],u) for v,u in cores.items())
            target={'lat':cores['supplied']['lat']+.9*budget/111.32,'lng':cores['supplied']['lng']}
            for variant in ('supplied','stock_zero'):
                state=states[variant];missions.validate(state);core=cores[variant]
                after=run(variant+'-96h-then-move',state,[dict(unit=core['name'],action='move',**target)])
                moved=next(u for _,u in missions.units(after) if u['historical_unit_id']=='ww2.jp.division106')
                moves[variant]=missions.distance(core,moved)
            assert moves['stock_zero']<moves['supplied']-1e-4,moves
            result.update(passed=True,resume_from=str(args.resume_stocks),movement_km=moves,common_movement_budget_km=budget,
                scope='Actual movement after retained96-hour supply contrast; no repeat or historical calibration')
            return
        s,p=inputs();world=ho.initial(s,p)
        held=run('hold-one-hour',world,[])
        orders=[]
        for team,u in missions.units(world):
            enemies=world[('blue' if team=='red' else 'red')+'_units']
            target=min(enemies,key=lambda e:missions.distance(u,e))
            if missions.distance(u,target)*1000<=world['mission']['definition']['combined_rules']['artillery_range_m']:
                orders.append(dict(unit=u['name'],action='bombard',target=target['name']))
            else:orders.append(dict(unit=u['name'],action='hold'))
        hit=run('bilateral-artillery-one-hour',world,orders)
        assert all(any(o['unit']==u['name'] for o in orders) for _,u in missions.units(world))
        assert len(hit['engagements'])>len(held['engagements'])
        assert all(sum(u['personnel']['casualties'] for u in hit[t+'_units'])>0 for t in ('red','blue'))
        snapshots={}
        for variant in ('supplied','stock_zero'):
            s,p=inputs();p['clock']['time_step']='6小时';p['goal']['deadline_turn']=20
            if variant=='stock_zero':p['support']['blue']['stock']=0
            state=ho.initial(s,p)
            for turn in range(1,17):
                state=run(variant+'-'+str(turn*6)+'h',state,[])
                if turn in (1,8,16):snapshots[(variant,turn)]=state
        for turn in (1,8,16):
            def core(variant):return next(u for _,u in missions.units(snapshots[(variant,turn)]) if u['historical_unit_id']=='ww2.jp.division106')
            assert core('stock_zero')['sustainment']['shortage_hours']>=core('supplied')['sustainment']['shortage_hours']
        assert core('stock_zero')['personnel']['noncombat_losses']>core('supplied')['personnel']['noncombat_losses']
        result.update(passed=True,explicit_single_factor='blue warehouse initial stock800 versus0',
            note='6-hour supply opportunities remain per-round; this experiment does not establish step-size invariance or person-mass calibration')
    except Exception as exc:result['error']=str(exc);raise
    finally:save();harness_engine.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
