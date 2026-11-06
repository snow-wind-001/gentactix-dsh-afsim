"""Normal API / real DSH skill build and one-sided native control."""
import argparse
import copy
import json
from pathlib import Path
import time
import uuid

from tools.qa.catalog_expansion_live import call,revision,advance
from tools.qa.noncontact_fixture import CASES


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('Use --live against owned isolated API18998')
    root=Path('.cache/qa/noncontact/live');root.mkdir(parents=True,exist_ok=True)
    def save(name,v):(root/(name+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
    health=call('GET','/api/health');assert not health['build']['restart_required']
    assert Path(f"/proc/{health['build']['pid']}/cmdline").read_bytes().split(b'\0')[1]==b'.cache/qa/ww2-phases/launch.py'
    battle,phase=CASES['LM13-jinsha1936'];operation=uuid.uuid4().hex
    save('build-operation',{'operation_id':operation})
    request={'battle':battle,'phase_id':phase,'operation_id':operation,'execution_backend':'afsim',
        'time_step':'1分钟','required_models':['formation-ferry-1'],
        'instruction':'非接敌局部链路QA，只有已有红12团ID，不添加蓝方。仅10人计算载荷，不是史实全团人数；'
        '所有5类装备、炮弹、防空弹药、燃油、施工材料、备件全部0，徒步。粮食弹药80；疲劳压制0；signal100。'
        '采用已给阶段时间范围，时钟25日18时起，1分钟，最多12轮。'
        '按石鼓地名附近估计南北两岸，相距约60米、有限河线，单位在南岸登船点；单船10座，'
        '速度0.5米/秒、装卸各10秒、初始岸a、装备容量0，明确是QA估计不是史实船型。'
        '目标红方crossing完成渡运到北岸并在20米内集结，required_survivors=1，required_turns=1。'
        '仓库全部库存0；蓝方support仅格式占位且stock和inventory全0，不能生成在场蓝方或仓库。'
        '公共规则command_base_s、command_signal_s、command_distance_s_per_km均0。'
        'facility.progress=0，不能把已有渡船说成历史建桥成功。不得生成历史战果。'}
    save('build-request',request);start=time.monotonic();print('START actual DSH non-contact skill build',operation,flush=True)
    draft=call('POST','/api/historical-scenarios/build',request);save('actual-draft',draft)
    assert draft['preview_world']['blue_units']==[] and len(draft['preview_world']['red_units'])==1
    assert {n['team'] for n in draft['preview_world']['supply_nodes']}=={'red'}
    assert draft['parameters']['actors'][next(iter(draft['parameters']['actors']))]['personnel']==10
    print('PASS build',round(time.monotonic()-start,3),flush=True)
    result={'passed':False,'draft_id':draft['id'],'build_seconds':round(time.monotonic()-start,3),
        'scope':'actual skill-generated small QA load, not full historical formation','sessions':{},'turns':[]}
    save('result',result)
    def create(engine,label,product='historical',derived=None):
        payload={'scenario':'非接敌渡运QA；实际历史身份、显式10人估计载荷，非全团史实实力',
            'battle':battle,'product_mode':product,'simulation_mode':'open','execution_backend':engine,
            'persist_roles':False,'time_step':'1分钟'}
        if derived:payload.update(mission_id=derived['draft']['mission_id'],scenario_draft_id=derived['draft']['id'],synthetic_configuration=derived['configuration'])
        else:payload['historical_parameters']=copy.deepcopy(draft['parameters'])
        sid=call('POST','/api/sessions',payload)['session_id'];result['sessions'][label]=sid;save('result',result)
        world=call('POST','/api/sessions/'+sid+'/init');save(label+'-initial',world)
        assert world['war_state']['blue_units']==[]
        return sid,world
    def run(sid,label,human=False):
        path='/api/sessions/'+sid;view=call('GET',path+'/commands')
        orders=[]
        if human:
            unit=view['units'][0];w=call('GET',path)['war_state'];target=w['combined_arms']['bridge']['crossing_model']['banks']['b']
            orders=[{'unit_id':unit['id'],'action':'move','destination':target,'duration':'until_arrived'}]
        call('PUT',path+'/commands',{**revision(view),'orders':orders,'director':True,'control_team':'red','no_fire':False,
            'unit_agents':[],'intent':'仅指挥在场单位通过登记渡运通道抵达对岸；没有在场对手，不射击。'})
        print('START',label,sid,flush=True);start=time.monotonic()
        answer=advance(sid,'请指挥唯一在场单位按登记渡运通道向出口岸集结。没有敌方单位，不添加蓝方、不射击、不造战斗损失。'
            '必须保留舟艇跨轮状态；等待或未到岸时不能瞬间宣布渡运完成。')
        save(label,answer);world=answer['war_state']
        assert world['blue_units']==[] and not world['engagements']
        assert world['red_units'][0]['personnel']['casualties']==0
        assert world['historical_initial']==draft['initial']
        result['turns'].append({'label':label,'session_id':sid,'turn':answer['turn_count'],
            'seconds':round(time.monotonic()-start,3),'status':world['mission']['status'],
            'crossing':world['red_units'][0].get('crossing'),'boat':world['combined_arms']['bridge']['ferry_state']['boats'][0]})
        save('result',result);print('PASS',label,world['mission']['status'],flush=True)
        return answer
    native,_=create('afsim','native')
    answer=run(native,'native-turn1')
    receipts=call('GET','/api/sessions/'+native+'/commands');save('native-first-command-view',receipts)
    assert receipts['receipts'] and answer['war_state']['mission']['last_orders'][0]['action']=='move'
    for turn in [2,3,4,5,6]:
        if answer['war_state']['mission']['status']=='completed':break
        answer=run(native,'native-turn'+str(turn),human=True)
    assert answer['war_state']['mission']['winner']=='red'
    pure,_=create('narrative','dsh');run(pure,'dsh-turn1',human=True)
    operation=uuid.uuid4().hex;save('derive-operation',{'operation_id':operation})
    derived=call('POST','/api/scenarios/from-historical',{'base_draft_id':draft['id'],'operation_id':operation,'execution_backend':'afsim'})
    save('synthetic-derived',derived);assert derived['configuration']['teams']['blue']==[]
    create('afsim','synthetic',product='synthetic',derived=derived)
    result['passed']=True;save('result',result)


if __name__=='__main__':main()
