"""Real fire-resupply contrast and22-actor120-hour resource continuity.

Explicit QA inputs; no historical loss fitting or model-generated decisions.
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
    parser.add_argument('--resume-long',type=Path,help='Resume a retained committed long-window checkpoint after a fix')
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    root=Path('.cache/qa/supply-schedule-2026-11-01/extended')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
        os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from gentactix import historical_operations as ho,missions,sim_clock,combat_effects
    from backend import afsim_world,afsim_rules,harness_engine
    from verify_supply_schedule import world,config
    from tools.qa.wanjialing_estimate_fixture import inputs
    result={'passed':False,'actual_afsim':True,'actual_model':False,'cases':[],
        'scope':'QA supply timing intervention and120-hour stationary resource continuity, not full historical Wanjialing acceptance'}
    def save():(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def run(label,before,orders=None):
        orders=orders or [];seconds=sim_clock.duration_seconds(before['mission']['definition']['time_step']);prior=copy.deepcopy(before)
        scene=afsim_world.compile_scene(before,orders,seconds,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('AFSIM required')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence.pop('native_effects'),scene['native_model'],scene,
                afsim_world.apply_observations(before,positions,scene))
        after['current_time'],after['simulation_clock']=sim_clock.target(before,before['mission']['definition']['time_step'])
        missions.evaluate(after);missions.validate(after);assert before==prior
        for _,u in missions.units(after):
            p=u['personnel'];assert p['committed']==p['current']+p['casualties']+p['noncombat_losses']
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        (root/(label+'.json')).write_text(json.dumps(after,ensure_ascii=False)+'\n')
        result['cases'].append({'label':label,'elapsed_s':after['simulation_clock']['elapsed_seconds'],
            'units':len(missions.units(after)),'native':evidence})
        save();print('PASS',label,flush=True);return after
    try:
        if args.resume_long:
            state=json.loads(args.resume_long.read_text());missions.validate(state)
            s=state['mission']['definition']['historical_calculation']['initial']
            result['resumed_from']=str(args.resume_long)
        else:
            base=world();binding=copy.deepcopy(base['mission']['definition']['historical_calculation'])
            p=binding['parameters']
            for actor in p['actors'].values():actor['logistics']['ammo']=2
            timed=ho.initial(binding['initial'],p)
            old=copy.deepcopy(p);old.pop('supply_schedule')
            legacy=ho.initial(binding['initial'],old)
            red=timed['red_units'][0];blue=timed['blue_units'][0]
            order=[{'unit':red['name'],'action':'fire','target':blue['name']}]
            a=run('fire-timed',timed,order);b=run('fire-legacy-end-only',legacy,order)
            receipts={label:next(r for r in w['mission']['ledger'] if r['unit']==red['name'])
                      for label,w in [('timed',a),('legacy',b)]}
            assert receipts['timed']['ammo_spent']>receipts['legacy']['ammo_spent']
            assert receipts['legacy']['ammo_spent']<=2
            result['fire_contrast']={label:{k:r[k] for k in ('ammo_spent','ammo_received','food_spent')} for label,r in receipts.items()}
            s,p=inputs();p['clock']['time_step']='6小时';p['supply_schedule']=config()
            p['supply_schedule']['assumption']='QA周期服务假设，静止待命120小时；不模拟历史行动、车队在途或武器损失。'
            for actor in p['actors'].values():actor['ground_control_radius_km']=0
            p['assumptions']+=' 本次为关闭道路阻断的定时保障连续性试验；不视为历史战术过程。'
            state=ho.initial(s,p)
        original=copy.deepcopy(state);events=0
        starting_turn=state['mission']['turn']+1
        for turn in range(starting_turn,21):
            state=run('campaign-'+str(turn*6)+'h',state)
            assert len(missions.units(state))==22
            events+=sum(len(row['events']) for row in state['supply_schedule']['ledger']['units'])
        assert state['simulation_clock']['elapsed_seconds']==120*3600
        for (_,first_unit),(_,last_unit) in zip(missions.units(original),missions.units(state)):
            assert first_unit['historical_unit_id']==last_unit['historical_unit_id']
            # Native provenance/breakdown metadata is added on first execution.
            # Compare physical balances, not the absence of that evidence atT0.
            for key in ('committed','current','casualties','noncombat_losses'):
                assert first_unit['personnel'][key]==last_unit['personnel'][key]
            for key in ('committed','operational','damaged','destroyed'):
                assert [e[key] for e in first_unit['equipment']]==[e[key] for e in last_unit['equipment']]
        result.update(passed=True,full_history_acceptance=False,campaign_units=22,campaign_hours=120,
            campaign_rounds=20,campaign_new_rounds=21-starting_turn,campaign_receipt_events=events,source_profile_version=s['version'])
    except Exception as exc:result['error']=str(exc);raise
    finally:save();harness_engine.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
