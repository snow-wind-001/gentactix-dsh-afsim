"""Normal API loading and actual dual-engine boat turns; explicit QA estimates."""
import argparse
import copy
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from verify_ferries import ferry_inputs

p=argparse.ArgumentParser();p.add_argument('--live',action='store_true')
if not p.parse_args().live:p.error('Owned QA API18998 and actual model access require --live')
root=Path('.cache/qa/ferry-model');base='http://127.0.0.1:18998'


def save(name,value):
    (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def call(method,path,value=None):
    req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
        data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(req,timeout=1200) as response:return json.load(response)
    except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:2500]) from e


checks=[]
def check(ok,label):
    if not ok:raise AssertionError(label)
    checks.append(label);save('live-checks',checks);print('PASS',label,flush=True)

health=call('GET','/api/health');check(not health['build']['restart_required'],'API uses current source')
for old in json.loads(Path('.cache/qa/formation-partitions/before-cold-restart.json').read_text()):
    state=call('GET','/api/sessions/'+old['session_id'])
    assert state['war_state']==old['world'] and state['turn_count']==old['turn']
    assert call('GET','/api/sessions/'+old['session_id']+'/commands')==old['commands']
check(True,'all original 44 QA worlds and commands unchanged')
parent=json.loads(Path('.cache/qa/formation-partitions/historical-draft.json').read_text())
snapshot,params=ferry_inputs()
identities=json.loads((root/'session-ids.json').read_text()) if (root/'session-ids.json').exists() else {}
operations=json.loads((root/'operations.json').read_text()) if (root/'operations.json').exists() else []
for engine in ('afsim','narrative'):
    if engine not in identities:
        operation=uuid.uuid4().hex;operations.append(operation);save('operations',operations)
        draft=call('POST','/api/historical-scenarios/validate',{'parameters':params,'parent_draft_id':parent['id'],
            'execution_backend':engine,'operation_id':operation})
        save(engine+'-draft',draft)
        check(draft['validation']['scope']==('native_load' if engine=='afsim' else 'configuration_contract_only'),engine+' normal validation scope')
        created=call('POST','/api/sessions',{'scenario':'舟艇过程QA（非历史复原）-'+engine,'battle':snapshot['definition']['battle'],
            'product_mode':'historical','execution_backend':engine,'persist_roles':False,'use_rag':True,
            'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id']})
        identities[engine]=created['session_id'];save('session-ids',identities)
    sid=identities[engine];path='/api/sessions/'+sid
    state=call('GET',path)
    if not state.get('war_state'):state=call('POST',path+'/init')
    if not (root/(engine+'-initial.json')).exists():save(engine+'-initial',state)
    before=copy.deepcopy(state['war_state'])
    if state['turn_count']==0:
        view=call('GET',path+'/commands')
        revision={k:view[v] for k,v in [('expected_turn','turn'),('revision','revision'),('world_version','world_version')]}
        orders=[{'unit_id':u['id'],'action':'move' if '先遣分队' in u['name'] else 'hold','duration':'until_arrived' if '先遣分队' in u['name'] else 'next',
            **({'destination':{'lat':27.3151,'lng':107.402}} if '先遣分队' in u['name'] else {})} for u in view['units']]
        call('PUT',path+'/commands',{**revision,'orders':orders,'control_team':'red','director':True,
            'no_fire':True,'intent':'仅按确认命令检验舟艇，不是1935年史实复原；无交火，无仓库库存，不改变兵力。','unit_agents':[]})
        view=call('GET',path+'/commands')
        revision={k:view[v] for k,v in [('expected_turn','turn'),('revision','revision'),('world_version','world_version')]}
        print('TURN',engine,'real execution',flush=True);start=time.monotonic()
        try:
            state=call('POST',path+'/next',{**revision,'batch_id':uuid.uuid4().hex,
                'instruction':'执行已确认的1分钟命令。仅五人计算分队到出口岸，其余单位hold。舟艇座位5，船速.5m/s、装卸各10秒；按已登记输入估计装载与实际航行，60秒内来不及登岸，不得completed。'
                'AFSIM关闭时由DSH提交完整舟艇状态、事件和crossing容量账，不使用桥梁progress0拒绝舟艇。'
                '粮食仍是0–100覆盖：五人move减少4，主队及其余hold减少2；收支按初始人数比重折算，delivery与ammo_spent均0。'
                '登船后船位与该分队位置一致，保留未渡主队，不新增兵力、船员、战斗或仓库货运。所有数字明确为QA估计，不声称对应历史先遣分队。'})
        except Exception as error:
            save(engine+'-failure',{'error':str(error),'elapsed_s':time.monotonic()-start});raise
        save(engine+'-timing',{'elapsed_s':time.monotonic()-start});save(engine+'-turn1',state)
    boat=state['war_state']['combined_arms']['bridge']['ferry_state']['boats'][0]
    part=next(u for u in state['war_state']['red_units'] if u.get('formation_part',{}).get('part_id')=='advance')
    check(boat['phase']=='outbound' and boat['manifest_personnel']==5 and boat['passenger']==part['name'],engine+' actual partial voyage without premature landing')
    check(abs(part['lat']-boat['lat'])<.00001,engine+' passenger follows boat location')
    check(state['war_state']['historical_initial']==before['historical_initial'],engine+' source facts preserved')
    check(sum(u['personnel']['current'] for u in state['war_state']['red_units'])==4600,engine+' no duplicate parent or boat crew force')
save('live-result',{'passed':True,'checks':checks,'session_ids':identities,'scope':'explicit QA assumptions, not full historical campaign acceptance'})
