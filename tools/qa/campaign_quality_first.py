"""Fresh turn-zero real probe for input-pending/turn-end narrative confusion."""
import argparse
import json
import uuid
from tools.qa.campaign_quality_live import call, ROOT, digest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live for an actual configured model call')
    from tools.qa.campaign_plan_fixture import inputs, NOTE
    source, parameters=inputs()
    folder=ROOT/'fresh-first';folder.mkdir(exist_ok=True)
    if (folder/'result.json').exists():raise SystemExit('Fresh probe already recorded; preserve it rather than overwrite')
    created=call('POST','/sessions',dict(scenario='首轮目标状态复核；'+NOTE,battle=source['definition']['battle'],
        time_step='30分钟',product_mode='historical',simulation_mode='open',execution_backend='narrative',
        agent_mode='native',historical_parameters=parameters,historical_initial_version='1.2.0'))
    base='/sessions/'+created['session_id'];before=call('POST',base+'/init')
    (folder/'initial.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
    view=call('GET',base+'/commands')
    call('PUT',base+'/commands',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],
        control_team='red',director=True,no_fire=False,intent='本轮双方全员待命，战报保留每个单位全名，只说明运动、资源及交火事实；本轮目标由宿主评分后追加，不重复初态状态。',
        orders=[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']]))
    view=call('GET',base+'/commands')
    after=call('POST',base+'/next',dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],batch_id=uuid.uuid4().hex))
    (folder/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
    trace=call('GET',base+'/traces/1');audit=trace['record']['guards']['report']
    (folder/'trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
    assert all(u['supply']==u['logistics']['food']==78 for team in ('red','blue') for u in after['war_state'][team+'_units'])
    assert 'pending' not in after['history'][0] and '第161师万家岭投入部' in after['history'][0]
    assert '当前条件成立；前置目标尚未达成' in after['history'][0]
    result=dict(passed=True,actual_model=True,physical_and_published_checks=True,raw_prose_screened=audit['status']=='screened',
        raw_prose_issues=audit['issues'],session_id=after['session_id'],turn=after['turn_count'],world_hash=digest(after['war_state']),meta=after['engine_meta'])
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('PASS fresh real first turn; raw prose screened =',result['raw_prose_screened'],flush=True)
