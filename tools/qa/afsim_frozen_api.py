"""Exercise a separately launched frozen backend without a model request."""
from pathlib import Path
import json
import urllib.request
import urllib.error
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:18902'


def request(method, path, data=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None,
        method=method, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def main():
    for attempt in range(40):
        try:
            health = request('GET', '/api/health')
            break
        except urllib.error.URLError:
            if attempt == 39:
                raise
            time.sleep(.5)
    assert health['afsim']['available']
    created = request('POST', '/api/sessions', {'scenario':'AFSIM冻结包固定局部验收',
        'mission_id':'AJ18-local-v1','execution_backend':'afsim','persist_roles':False})
    sid = created['session_id']; path = '/api/sessions/' + sid
    initial = request('POST', path + '/init')
    view = request('GET', path + '/commands')
    def revision(view):
        return {'expected_turn':view['turn'],'revision':view['revision'],'world_version':view['world_version']}
    orders=[{'unit_id':unit['id'],'action':'hold','duration':'next'} for unit in view['units']]
    actor=next(u for u in view['units'] if u['team']=='red')
    target=next(u for u in view['units'] if u['team']=='blue')
    next(o for o in orders if o['unit_id']==actor['id']).update(action='air_support',target_id=target['id'])
    view = request('PUT', path + '/commands', {**revision(view),'director':True,'orders':orders})
    final = request('POST', path + '/next', {**revision(view),'batch_id':'frozen-manual-round'})
    assert final['turn_count'] == 1 and final['afsim']['model_skipped'] is True
    assert final['afsim']['source'] == 'dsh_native_mcp_controller' and final['afsim']['returncode'] == 0
    assert len(final['war_state']['red_units']) == len(initial['war_state']['red_units'])
    air=final['war_state']['air_operations'];assert air['assets']['red']['ready']==7
    victim=final['war_state']['blue_units'][0]
    assert victim['personnel']['casualties']==6 and victim['equipment'][0]['destroyed']==1
    assert victim['last_combat_effects']['air_casualties']==6
    assert final['afsim']['effects_source'].startswith('afsim-native-')
    report = {'passed':True,'frozen_api':True,'native_dsh_mcp':True,'real_afsim':True,'model_called':False,
        'turns':final['turn_count'],'entities':final['afsim']['entity_count'],'session_id':sid,
        'native_air_operations':True,'air_assets':air['assets']['red'],'actual_air_casualties':6,'actual_equipment_losses':1}
    directory = ROOT / '.cache/qa/afsim-bridge/frozen-api'; directory.mkdir(parents=True,exist_ok=True)
    (directory / 'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
