"""Opt-in native checks of goal ownership, movement, contention and elimination.

Sourced identity is preserved; counts, points and conditions here are explicit
software-test estimates, not a reconstructed Maryang San operation.
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
    if not parser.parse_args().live:parser.error('Real native checks require --live')
    out=Path('.cache/qa/objective-team/native')/str(time.time_ns());out.mkdir(parents=True)
    (out.parent/'latest.json').write_text(json.dumps({'directory':str(out)}))
    for key,suffix in (('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),
        ('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')):
        os.environ['GENTACTIX_'+key]=str(out.resolve()/suffix)
    from backend import afsim_world,afsim_rules
    from gentactix import historical_operations as ho,missions,sim_clock
    from tools.qa.korean_series_fixture import inputs
    records=[]

    def create(profile='assault',*,red_offset=.012,blue_offset=-.004,deadline=3,red_count=None,blue_count=None):
        snapshot,p=inputs('KW06-autumn1951');center=p['area']['center']
        for identity,actor in p['actors'].items():
            red=identity=='kw.cn.regiment571';offset=red_offset if red else blue_offset
            actor['position']={'lat':center['lat']+offset,'lng':center['lng']}
            count=red_count if red else blue_count
            if count is not None:actor['personnel']=count
            actor['assumption']+=' 本次仅验证目标裁决：人数与部署是软件边界输入，不是史实实到量。'
        p['goal'].update(team='blue',profile=profile,objective=copy.deepcopy(center),radius_km=.2,
            exit={'lat':center['lat']-.008,'lng':center['lng']},deadline_turn=deadline,required_turns=2)
        p['rules']['goal_profile']=profile
        return ho.initial(snapshot,p)

    def step(label,world,orders):
        old=copy.deepcopy(world);scene=afsim_world.compile_scene(world,orders,1800,native_rules=True)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            positions,evidence=afsim_world.run_scene({},scene)
            after=afsim_rules.apply_telemetry(evidence['native_effects'],scene['native_model'],scene,
                afsim_world.apply_observations(world,positions,scene))
        assert world==old
        after['current_time'],after['simulation_clock']=sim_clock.target(world,'30分钟')
        after['afsim']={k:v for k,v in evidence.items() if k!='native_effects'}
        missions.validate(after)
        (out/(label+'-'+str(after['mission']['turn'])+'.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2))
        return after

    def move(world,team,point):return [{'unit':world[team+'_units'][0]['name'],'action':'move',**point}]
    def run(label,fn):
        record={'case':label,'passed':False,'historical_fit_verified':False};records.append(record)
        try:
            world=fn();record.update(passed=True,turn=world['mission']['turn'],winner=world['mission']['winner'],
                objective_team=world['mission']['definition']['objective_team'],metrics=world['mission']['metrics'])
            print(label,'PASS',record['winner'],record['turn'],flush=True)
        except Exception as exc:record['error']=str(exc);raise
        finally:(out/'results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')

    def capture():
        w=create();goal=w['mission']['definition']['objective']
        w=step('capture',w,move(w,'blue',goal));assert w['mission']['progress']==1 and w['mission']['status']=='active'
        w=step('capture',w,[]);assert w['mission']['winner']=='blue';return w
    run('blue_move_then_control',capture)

    def no_move():
        w=create()
        for _ in range(3):w=step('no-move',w,[])
        assert w['mission']['winner']=='red' and w['mission']['progress']==0;return w
    run('same_positions_without_blue_move_fail',no_move)

    def contested():
        w=create(red_offset=.0005,blue_offset=-.0005)
        for _ in range(3):w=step('contested',w,[])
        assert w['mission']['metrics']['red_in_goal']==1 and w['mission']['metrics']['blue_in_goal']==1
        assert w['mission']['winner']=='red' and w['mission']['progress']==0;return w
    run('contested_goal_is_not_captured',contested)

    def interrupted():
        w=create(blue_offset=0,deadline=4);goal=w['mission']['definition']['objective']
        w=step('interrupted',w,[]);assert w['mission']['progress']==1
        away={'lat':goal['lat']-.005,'lng':goal['lng']}
        w=step('interrupted',w,move(w,'blue',away));assert w['mission']['progress']==0
        w=step('interrupted',w,move(w,'blue',goal));assert w['mission']['progress']==1
        w=step('interrupted',w,[]);assert w['mission']['winner']=='blue';return w
    run('leaving_resets_consecutive_control',interrupted)

    def breakout():
        w=create('breakout');exit=w['mission']['definition']['exit']
        w=step('breakout',w,move(w,'blue',exit));assert w['mission']['progress']==1
        w=step('breakout',w,[]);assert w['mission']['winner']=='blue';return w
    run('blue_breakout_counts_blue_exit',breakout)

    def delay():
        w=create('delay',deadline=2)
        for _ in range(2):w=step('delay',w,[])
        assert w['mission']['winner']=='blue';return w
    run('blue_delay_survives_to_deadline',delay)

    def breach():
        w=create('delay',red_offset=-.008,deadline=2)
        for _ in range(2):w=step('breach',w,[])
        assert w['mission']['winner']=='red';return w
    run('red_at_exit_defeats_blue_delay',breach)

    def blue_eliminated():
        w=create(red_offset=.004,blue_offset=0,red_count=4500,blue_count=12)
        w=step('blue-eliminated',w,[{'unit':w['red_units'][0]['name'],'action':'fire','target':w['blue_units'][0]['name']}])
        assert w['blue_units'][0]['personnel']['current']==0 and w['mission']['winner']=='red';return w
    run('blue_elimination_ends_blue_goal',blue_eliminated)

    def red_eliminated():
        w=create(red_offset=.009,blue_offset=.004,red_count=12,blue_count=4500)
        w=step('red-eliminated',w,[{'unit':w['blue_units'][0]['name'],'action':'fire','target':w['red_units'][0]['name']}])
        assert w['red_units'][0]['personnel']['current']==0 and w['mission']['status']=='active'
        goal=w['mission']['definition']['objective'];w=step('red-eliminated',w,move(w,'blue',goal))
        w=step('red-eliminated',w,[]);assert w['mission']['winner']=='blue';return w
    run('red_elimination_does_not_fake_blue_control',red_eliminated)


if __name__=='__main__':main()
