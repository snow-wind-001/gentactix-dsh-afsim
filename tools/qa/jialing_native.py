"""Opt-in real API -> DSH native plugin -> AFSIM checks on Jialing local phases.

All orders are controlled; no LLM or Python combat fallback is permitted. This
checks import, command effects, transport capacity and observations, not full
campaign history, multi-site coupling or recovered historical weapon effects.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time
import uuid
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    if not args.native:
        parser.error('--native required')
    root = Path('.cache/qa/jialing-native-2026-10-29') / str(time.time_ns())
    root.mkdir(parents=True)
    for key, suffix in [('SESSION_DIR','sessions'), ('TRACE_DIR','traces'), ('DSH_HOME','home'),
                        ('DSH_WORKSPACE','workspace'), ('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key] = str(root.resolve()/suffix)
    os.environ['GENTACTIX_LLM_CONFIG'] = str(args.config.resolve())
    from fastapi.testclient import TestClient
    from backend import main as api, session_store, harness_engine as h, runtime_bridge, agent_tools
    from gentactix import missions, sim_clock
    from tools.qa.jialing_fixture import inputs, PHASES
    runtime_bridge.register_dispatcher(api._native_tool_dispatch)
    client = TestClient(api.app)
    result = {'passed':False, 'model_calls':0, 'historical_fit_verified':False,
              'multi_site_campaign_verified':False, 'cases':[]}

    def write(name, value):
        (root/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

    def revision(view):
        return {k:view[v] for k,v in [('expected_turn','turn'), ('revision','revision'), ('world_version','world_version')]}

    def create(label, phase, *, throughput=1200, empty_shells=False):
        source, parameters = inputs(phase, throughput=throughput)
        if empty_shells:
            parameters['actors']['jl.red.artillery']['formation']['shells'] = 0
        basis = client.get('/api/historical-scenarios/basis', params={
            'battle':source['definition']['battle'], 'phase_id':phase, 'time_step':'30分钟'})
        assert basis.status_code == 200 and basis.json()['ready'], basis.text
        assert basis.json()['initial']['phase_id'] == phase
        created = client.post('/api/sessions', json={
            'scenario':'嘉陵江原生受控QA：'+label, 'battle':source['definition']['battle'],
            'historical_parameters':parameters, 'time_step':'30分钟', 'execution_backend':'afsim',
            'simulation_mode':'open', 'product_mode':'historical', 'persist_roles':False})
        assert created.status_code == 200, created.text
        session = api._SESSIONS[created.json()['session_id']]
        path = '/api/sessions/'+session['id']
        response = client.post(path+'/init')
        assert response.status_code == 200, response.text
        world = response.json()['war_state']
        assert world['historical_initial'] == source
        assert world['afsim']['returncode'] == 0 and world['afsim']['entity_count'] == len(parameters['actors'])
        write(label+'-initial', response.json())
        return session, path

    def step(label, session, path, mode):
        before = copy.deepcopy(session['war_state'])
        view = client.get(path+'/commands').json()
        roster = {u['name']:u for _,u in missions.units(before)}
        orders = []
        for item in view['units']:
            unit = roster[item['name']]
            order = {'unit_id':item['id'], 'action':'hold', 'duration':'next'}
            if mode == 'cross' and item['team'] == 'red' and unit['formation']['role'] != 'support':
                if unit.get('crossing',{}).get('status') != 'completed':
                    order.update(action='move', duration='until_arrived',
                                 destination=copy.deepcopy(before['mission']['definition']['objective']))
                    # Preserve the actual user's continuing order, rather than
                    # cancelling and replacing its intent on every turn.
                    previous = next((o for o in view['orders'] if o['unit_id'] == item['id']), None)
                    if previous:
                        order['id'] = previous['id']
            if mode == 'fire' or (mode in ('artillery','empty_shells') and unit['historical_unit_id'] == 'jl.red.artillery'):
                target = next(u for u in view['units'] if u['team'] != item['team'])
                order.update(action='fire' if mode == 'fire' else 'bombard', target_id=target['id'])
            orders.append(order)
        response = client.put(path+'/commands', json={**revision(view), 'orders':orders,
            'control_team':'red', 'director':True, 'no_fire':False, 'intent':'受控QA输入；不是历史命令。'})
        if mode == 'empty_shells':
            assert response.status_code == 422 and '炮弹库存不足' in response.text, response.text
            assert session['war_state'] == before
            assert client.get(path+'/commands').json() == view
            write(label+'-rejection', response.json())
            # A refused attack must not secretly execute. Advance under explicit
            # hold orders and compare with the otherwise identical armed case.
            response = client.put(path+'/commands', json={**revision(view),
                'orders':[{'unit_id':u['id'],'action':'hold','duration':'next'} for u in view['units']],
                'control_team':'red','director':True,'no_fire':False,'intent':'缺弹命令已拒绝，保持待命。'})
        assert response.status_code == 200, response.text
        view = client.get(path+'/commands').json()
        request = {**revision(view), 'batch_id':uuid.uuid4().hex}
        response = client.post(path+'/next', json=request)
        assert response.status_code == 200, response.text
        snapshot = response.json(); after = snapshot['war_state']; native = after['afsim']; turn = session['turn_count']
        write(label+'-turn'+str(turn), snapshot)
        assert native['returncode'] == 0 and native['model_skipped']
        assert after['current_time'] == sim_clock.target(before, '30分钟')[0]
        assert after['historical_initial'] == before['historical_initial']
        assert {u['name'] for _,u in missions.units(after)} == set(roster)
        for _,unit in missions.units(after):
            p = unit['personnel']
            assert p['committed'] == p['current']+p['casualties']+p['noncombat_losses']
            assert p['casualties'] == sum(p.get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties'))
            assert all(e['committed'] == e['operational']+e['damaged']+e['destroyed'] for e in unit['equipment'])
        decisions = client.get(path+f'/unit-decisions?start_turn={turn}&end_turn={turn}').json()['items']
        assert len(decisions) == len(roster)
        observed = agent_tools.execute_tool_call(session, after, {'tool':'get_afsim_observation','args':{'limit':16,'detail':True}})
        assert observed['ok'] and observed['execution']['verified'] and len(observed['units']) == len(roster)
        for row in observed['units']:
            unit = next(u for _,u in missions.units(after) if u['name'] == row['name'])
            assert row['position'] == {'lat':unit['lat'], 'lng':unit['lng']}
            assert row['personnel']['current'] == unit['personnel']['current']
        write(label+'-observation'+str(turn), observed); write(label+'-decisions'+str(turn), decisions)
        replay = client.post(path+'/next', json=request)
        assert replay.status_code == 200 and replay.json()['command_result']['replayed']
        restored, errors = session_store.load_all()
        assert not errors and restored[session['id']]['war_state'] == after
        bridge = after['combined_arms']['bridge']; receipt = bridge.get('crossing_receipt', {})
        if receipt:
            assert receipt['used_work']+receipt['cargo_work'] <= receipt['budget_work']+.003
        summary = {'case':label, 'turn':turn, 'entities':len(roster),
            'crossed':sum(u.get('crossing',{}).get('status') == 'completed' for u in after['red_units']),
            'served_work':sum(u.get('crossing',{}).get('served_work',0) for u in after['red_units']),
            'mission_progress':after['mission']['progress'],
            'casualties':{t:sum(u['personnel']['casualties'] for u in after[t+'_units']) for t in ('red','blue')},
            'native_artifact':native['artifact']}
        result['cases'].append(summary); write('result',result); print(summary,flush=True)
        return after

    try:
        with patch.object(h, 'get_ai_response', side_effect=AssertionError('No LLM in controlled native checks')), \
             patch.object(missions, 'advance', side_effect=AssertionError('No Python combat fallback')):
            first = None
            for phase in PHASES[:-1]:
                session,path = create(phase,phase)
                for turn in range(4):
                    world = step(phase,session,path,'cross')
                    if phase == PHASES[0] and turn == 0:
                        first = copy.deepcopy(world)
                    if world['mission']['progress'] > 0:
                        break
                assert world['mission']['progress'] > 0
                assert all(u['personnel']['casualties'] == 0 for _,u in missions.units(world))
            session,path = create('hold',PHASES[0]); held = step('hold',session,path,'hold')
            assert not any(u.get('crossing') for u in held['red_units']) and held['mission']['progress'] == 0
            session,path = create('slow',PHASES[0],throughput=300); slow = step('slow',session,path,'cross')
            work = lambda w:sum(u.get('crossing',{}).get('served_work',0) for u in w['red_units'])
            assert 0 < work(slow) < work(first)
            session,path = create('artillery',PHASES[0]); fired = step('artillery',session,path,'artillery')
            session,path = create('empty-shells',PHASES[0],empty_shells=True); empty = step('empty-shells',session,path,'empty_shells')
            assert sum(u['personnel']['casualties'] for u in fired['blue_units']) > 0
            assert sum(u['personnel']['casualties'] for u in empty['blue_units']) == 0
            session,path = create('jianmen-fire',PHASES[-1]); fought = step('jianmen-fire',session,path,'fire')
            assert all(sum(u['personnel']['casualties'] for u in fought[t+'_units']) > 0 for t in ('red','blue'))
            assert 'crossing_model' not in fought['combined_arms']['bridge']
        result['passed'] = True
    finally:
        h.close_harness(); write('result',result)
        (root.parent/'latest.json').write_text(json.dumps({'directory':str(root)})+'\n')
        print(root,flush=True)


if __name__ == '__main__':
    main()
