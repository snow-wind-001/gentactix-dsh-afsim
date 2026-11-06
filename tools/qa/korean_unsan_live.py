"""Real nine-actor Unsan build and four-hour native execution; estimates only."""
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

from gentactix import missions
from tools.qa.korean_first_fixture import BATTLE


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--port',type=int,default=18998);p.add_argument('--out',type=Path,default=Path('.cache/qa/korean-first'))
    p.add_argument('--resume-session', help='Retry the preserved turn-zero QA battle with its existing real draft; do not rebuild')
    args=p.parse_args()
    if not args.live or not 18900<=args.port<=18999:p.error('Use --live with an isolated QA service')
    root=args.out;root.mkdir(parents=True,exist_ok=True);base=f'http://127.0.0.1:{args.port}'
    result={'passed':False,'checks':[],'historical_fit_verified':False}
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def call(method,path,value=None):
        req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=None if value is None else json.dumps(value,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as response:return json.load(response)
        except urllib.error.HTTPError as exc:raise RuntimeError(str(exc.code)+': '+exc.read().decode()[:1800]) from exc
    def view(sid):
        v=call('GET',f'/api/sessions/{sid}/commands')
        return v,{'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    def advance(sid,orders=None,instruction=''):
        v,rev=view(sid)
        if orders is not None:
            call('PUT',f'/api/sessions/{sid}/commands',{**rev,'orders':orders,'control_team':'red','director':True,
                'no_fire':False,'unit_agents':[],'intent':instruction});v,rev=view(sid)
        after=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
        save('unsan-turn'+str(after['turn_count']),after)
        for _,u in missions.units(after['war_state']):
            a=u['personnel'];assert a['committed']==a['current']+a['casualties']+a['noncombat_losses']
            assert a['casualties']==sum(a.get(k) or 0 for k in ('killed','wounded','missing','captured','unclassified_casualties'))
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        return after
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        operation=uuid.uuid4().hex;save('unsan-operation',{'operation_id':operation})
        instruction=('云山11月1日晚地面窗口：1950-11-01 17:00起，30分钟回合，8轮到21:00。'
            'goal.profile=delay，required_survivors=1，exit在云山旧城以南约3km，禁止用历史歼灭人数做目标。'
            '区域仅取已有云山旧城39.97278/125.80528周边，area半径8km，不能使用温井（今Unsan）或扩大到整场战役。'
            '保留已分配全部9个真实ID，不把美骑兵当骑马，不扩充炮兵连和坦克配属排为全营。'
            '数值配额全部是QA估计，非史实实到量：115、116、117师各5000人；美8骑兵团1营650、2营600、3营700，韩15团1800；99野炮营C连180，70坦克营B连配属排25人。'
            '红方各师支援火炮配额6门、shells=400，其他单位火炮0，只有美99野炮C连4门、shells=300；坦克仅70坦克营配属排4辆；全部防空配额0。'
            '红方徒步motorized=false燃油0；美军可motorized=true燃油1000，韩国步兵可徒步。每单位粮弹工作量80；其他库存合理估计。'
            '按来源相对方位展开：红115西南、116西北、117东北；美1营城北、2营城西、3营城南预备，韩15团右翼，C炮兵连城南，坦克排靠近3营。'
            '局部相距约0.5—1.5km，直射范围1000—1200m，火炮可覆盖本局部范围，不要所有单位重叠。'
            'terrain_factor=1.5，步兵速度3km/h，机动车型可6km/h。桥梁禁用；后方保障分别在各自后方，不能置于enemy exit。'
            '说明未绑定全配属、航空、次日援军与精确地形，21时是模型截止非战史停火；所有人数、装备、库存、坐标逐单位注明估计，不宣称完整复原。')
        if args.resume_session:
            draft=json.loads((root/'unsan-draft.json').read_text())
            result['reused_existing_real_draft']=True
        else:
            started=time.monotonic();draft=call('POST','/api/historical-scenarios/build',{'battle':BATTLE,'phase_id':'unsan_evening',
                'instruction':instruction,'operation_id':operation,'execution_backend':'afsim'});save('unsan-draft',draft)
            result['build_seconds']=round(time.monotonic()-started,2)
        check(draft['afsim']['entity_count']==9 and draft['afsim']['returncode']==0,'real native DSH staged build loads nine AFSIM actors')
        check(draft['construction']['workflow']=='native_agent_registry_scoped_drafts' and len(draft['construction']['stages'])==5,'native coordinator and three source-bound actor pages')
        parameters=draft['parameters']
        check(parameters['goal']['deadline_turn']==8 and parameters['goal']['profile']=='delay','eight-turn executable local goal configured')
        if args.resume_session:
            sid=args.resume_session;initial=call('GET',f'/api/sessions/{sid}')
            frozen=json.loads((root/'unsan-initial.json').read_text())
            check(initial['turn_count']==0 and initial['war_state']==frozen['war_state'],
                'failed planner left exact original nine-actor world at turn zero')
        else:
            sid=call('POST','/api/sessions',{'scenario':'云山九单位参数化QA；人数装备部署是显式估计，非完整历史复原','battle':BATTLE,
                'product_mode':'historical','execution_backend':'afsim','historical_parameters':parameters,'scenario_draft_id':draft['id'],'persist_roles':False})['session_id']
            initial=call('POST',f'/api/sessions/{sid}/init');save('unsan-initial',initial)
        result['session_id']=sid
        check(len(list(missions.units(initial['war_state'])))==9,'nine actual combat/support entities initialized')
        snap=advance(sid,instruction='先get_afsim_observation(limit=16)读全9个单位，不能只看初始8项。双方每个可行动单位明确下令。红方三个师根据实际射程、炮弹与情报接敌或炮击；蓝方步兵、炮兵与坦克排合理防御、还击或撤离。先核验有疑问命令，不得漏交蓝方，不强制历史战果。')
        check(not snap['war_state']['afsim']['model_skipped'] and len(snap['war_state']['afsim']['orders'])==9,'real DSH pages beyond the initial sample and plans every actor on both sides')
        v,_=view(sid);mover=next(u for u in snap['war_state']['red_units'] if u['personnel']['current']>0)
        point={'lat':mover['lat']+.0005,'lng':mover['lng']};registry={u['name']:u for u in v['units']}
        alive={u['name'] for _,u in missions.units(snap['war_state']) if u['personnel']['current']>0}
        orders=[{'unit_id':u['id'],'action':'move' if u['name']==mover['name'] else 'hold','duration':'next',
            **({'destination':point} if u['name']==mover['name'] else {})} for u in v['units'] if u['name'] in alive]
        snap=advance(sid,orders,'选中历史师并向地图指定位置移动，其他单位明确待命')
        actual=next(u for u in snap['war_state']['red_units'] if u['name']==mover['name'])
        check(abs(actual['lat']-point['lat'])<1e-5 and abs(actual['lng']-point['lng'])<1e-5,'selected zero-fuel foot formation reaches its explicit map destination')
        world=copy.deepcopy(snap['war_state']);v,rev=view(sid)
        branch=call('POST',f'/api/sessions/{sid}/commands/compare',{**rev,'turn':2,
            'orders':[{'unit_id':registry[mover['name']]['id'],'action':'hold','duration':'next'}]});save('unsan-counterfactual',branch)
        alternative=next(u for u in branch['alternative']['red_units'] if u['name']==mover['name'])
        check(abs(alternative['lat']-mover['lat'])<1e-5 and call('GET',f'/api/sessions/{sid}')['war_state']==world,'native command intervention changes position and preserves main world')
        for turn in range(3,9):
            v,_=view(sid);registry={u['name']:u for u in v['units']};orders=[]
            for team in ('red','blue'):
                for u in snap['war_state'][team+'_units']:
                    if u['personnel']['current']<=0:continue
                    action='resupply' if turn==4 else 'recon' if turn==5 else 'restore_comms' if turn==6 else 'hold'
                    order={'unit_id':registry[u['name']]['id'],'action':action,'duration':'next'}
                    enemies=[e for e in snap['war_state']['blue_units' if team=='red' else 'red_units'] if e['personnel']['current']>0]
                    if turn in (3,7,8) and enemies:
                        target=min(enemies,key=lambda e:missions.distance(u,e));distance=missions.distance(u,target)*1000
                        artillery=next((e['operational'] for e in u['equipment'] if e['category']=='artillery'),0)
                        cfg=snap['war_state']['mission']['definition']['combined_rules']
                        if artillery and u['formation']['shells']>0 and cfg['artillery_min_range_m']<=distance<=cfg['artillery_range_m'] and u['logistics']['ammo']>0:
                            order.update(action='bombard',target_id=registry[target['name']]['id'])
                        elif distance<=u['attack_range'] and u['logistics']['ammo']>0:order.update(action='fire',target_id=registry[target['name']]['id'])
                    orders.append(order)
            snap=advance(sid,orders,'明确火力、补给、侦察和通信动作；不匹配历史战果配额')
            check(snap['turn_count']==turn and snap['war_state']['historical_initial']==initial['war_state']['historical_initial'],f'turn{turn} native clock, source facts and personnel/equipment continuity')
        check(snap['war_state']['current_time'].endswith('21:00') and snap['war_state']['simulation_clock']['elapsed_seconds']==14400,'four-hour phase boundary respected exactly')
        final=copy.deepcopy(snap['war_state'])
        answer=call('POST',f'/api/sessions/{sid}/chat',{'message':'调用get_afsim_observation(limit=16)读取全部9个历史单位和get_afsim_changes核对本轮变化。简述双方累计战斗减员、火力弹耗、坦克排与炮兵连实际状态，区分估计参数和史料事实，不把模型截止21时当作史实停火。'});save('unsan-analysis',answer)
        check(answer['war_state']==final and answer['engine_meta']['finish_reason']=='completed','real DSH observes native final state without mutation')
        result.update(passed=True,totals={t:sum(u['personnel']['casualties'] for u in final[t+'_units']) for t in ('red','blue')})
        save('unsan-result',result)
    except Exception as exc:
        result['error']=str(exc);save('unsan-result',result);raise


if __name__=='__main__':main()
