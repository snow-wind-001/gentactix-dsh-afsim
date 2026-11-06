"""Opt-in real source-bound resource accounts with both existing executors.

Counts, deployments and deliveries are explicit QA assumptions. This checks
accounting and provenance, not calibrated transport or historical effectiveness.
"""
import argparse
import copy
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Resume only the saved owned QA sessions after a rejected candidate; preserve previous evidence')
    args=parser.parse_args()
    if not args.live:parser.error('Use --live against the owned isolated API18998')
    root=Path('.cache/qa/dsh-resources');result={'passed':False,'checks':[],'historical_fit_verified':False}
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    def check(ok,label):
        if not ok:raise AssertionError(label)
        result['checks'].append(label);print('PASS',label,flush=True)
    def call(method,path,data=None,expected=200):
        req=urllib.request.Request('http://127.0.0.1:18998'+path,method=method,
            headers={'Content-Type':'application/json'},data=None if data is None else json.dumps(data,ensure_ascii=False).encode())
        try:
            with urllib.request.urlopen(req,timeout=1200) as f:status,value=f.status,json.load(f)
        except urllib.error.HTTPError as exc:status,value=exc.code,json.loads(exc.read())
        if status!=expected:raise RuntimeError(str(status)+': '+str(value)[:1800])
        return value
    def revision(sid):
        v=call('GET',f'/api/sessions/{sid}/commands')
        return v,{'expected_turn':v['turn'],**{k:v[k] for k in ('revision','world_version')}}
    def world(sid):return call('GET',f'/api/sessions/{sid}')['war_state']
    try:
        check(not call('GET','/api/health')['build']['restart_required'],'fresh source API')
        parent=json.load(open('.cache/qa/objective-team/current-draft.json'));params=copy.deepcopy(parent['parameters'])
        center=params['area']['center'];facts={u['id']:u for u in parent['initial']['definition']['units']}
        for identity,actor in params['actors'].items():
            team=facts[identity]['team'];actor['position']={'lat':center['lat']+(.012 if team=='red' else -.012),'lng':center['lng']}
            actor['assumption']+='；资源QA部署：双方距中心南北各约1.3km，不是史实阵地；红方本窗不分配运输任务。'
        params['goal'].update(team='blue',profile='delay',deadline_turn=6,required_turns=1,required_survivors=1)
        params['rules'].update(goal_profile='delay',required_survivors=1)
        params['assumptions']+='；本次资源账QA仅测试明确移动/待命/小批补给，不复演史实或标定运输吞吐；目标为6轮局部存续测试。'
        sessions=json.load(open(root/'session-ids.json')) if args.resume else {}
        result['resumed_after_explicit_connectivity_enum_fix']=args.resume
        for engine in ('afsim','narrative'):
            draft=json.load(open(root/(engine+'-draft.json'))) if args.resume else call('POST','/api/historical-scenarios/validate',{'parameters':params,'parent_draft_id':parent['id'],
                'execution_backend':engine,'operation_id':uuid.uuid4().hex})
            if not args.resume:save(engine+'-draft',draft)
            check(bool(draft['afsim'])==(engine=='afsim'),engine+' validation uses the selected executor')
            sid=sessions[engine] if args.resume else call('POST','/api/sessions',{'scenario':'马良山具名单位资源账QA-'+engine+'；数值部署为估计',
                'battle':parent['initial']['definition']['battle'],'product_mode':'historical','execution_backend':engine,
                'historical_parameters':draft['parameters'],'scenario_draft_id':draft['id'],'persist_roles':False,'use_rag':True})['session_id']
            sessions[engine]=sid;save('session-ids',sessions)
            initial=json.load(open(root/(engine+'-initial.json'))) if args.resume else call('POST',f'/api/sessions/{sid}/init')
            if not args.resume:save(engine+'-initial',initial)
            check(initial['war_state']['historical_initial']==parent['initial'],engine+' sourced identities/facts are unchanged')
        sid=sessions['afsim'];before=world(sid)
        for turn in (1,2):
            v,rev=revision(sid);units={u['name']:u for team in ('red','blue') for u in before[team+'_units']}
            orders=[{'unit_id':u['id'],'action':'move' if turn==1 else 'hold','duration':'next',
                **({'destination':{'lat':units[u['name']]['lat']+.0009,'lng':units[u['name']]['lng']}} if turn==1 else {})} for u in v['units']]
            if args.resume:current=json.load(open(root/('afsim-turn'+str(turn)+'.json')))
            else:
                call('PUT',f'/api/sessions/{sid}/commands',{**rev,'control_team':'red','director':True,'no_fire':True,'unit_agents':[],'orders':orders})
                _,rev=revision(sid);current=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex})
                save('afsim-turn'+str(turn),current)
            before=current['war_state']
            check(before['afsim']['model_skipped'],'native turn '+str(turn)+' uses explicit manual orders')
            check(all(r['food_spent']==(4 if turn==1 else 2) and r['delivery_basis']=='native_gross_receipt'
                for r in before['mission']['ledger']),'native turn '+str(turn)+' retains existing food demand and labelled gross receipts')
        native_before=copy.deepcopy(before)
        answer=json.load(open(root/'native-analysis.json')) if args.resume else call('POST',f'/api/sessions/{sid}/chat',{'message':
            '只读核验：请按自开局到当前的完整资源账，逐单位列累计毛到货、粮食消耗、弹药消耗和当前粮食。'
            '说明为什么库存净变化不能作为到货或消耗；不要用本轮费用乘总轮数。实际读取工具后简短回答，不下令。'})
        if not args.resume:save('native-analysis',answer)
        check(answer['engine_meta']['finish_reason']=='completed' and answer['war_state']==native_before and world(sid)==native_before,
            'real DSH native resource analysis is readonly')
        from backend import afsim_state
        exported=call('GET',f'/api/sessions/{sid}/export')['session'];summary=afsim_state.changes(exported,{'mode':'aggregate'})
        save('native-aggregate',summary)
        check(all(r['logistics_workload']['totals']['food_spent']['known_sum']==6 for r in summary['units']),
            'existing aggregate tool sums move4 plus hold2 rather than multiplying the last round')
        check(any(r['logistics_workload']['totals']['delivery']['known_sum']>0 for r in summary['units']),
            'native transport has actual positive gross delivery evidence')
        sid=sessions['narrative'];committed=call('GET',f'/api/sessions/{sid}')['turn_count']
        if args.resume:
            expected=json.load(open(root/('narrative-turn'+str(committed)+'.json')))['war_state']
            check(world(sid)==expected,'rejected model candidate preserved the exact last committed world before resume')
        before=json.load(open(root/'narrative-initial.json'))['war_state']
        instructions=[
            'AFSIM关闭；这是明确的人为资源账QA，不是历史命令。双方都move到各自轮初位置正北约100米，不开火。双方本轮不组织补给，到货全部0；按现有工作量每单位粮食消耗4，蓝方摩托化移动申报至少1升燃油消耗，分类到货0。完整提交resource_ledger和对应库存更新，来源事实不改。',
            '双方全部hold，无交火，无任何到货。每单位粮食工作量消耗2，不能把待命解释为不消耗。保留人员装备，完整收支账与期末库存必须相符。',
            '双方resupply，无交火。红方本轮未分配运输任务，到货0，粮食消耗2。蓝方只安排一个估计小批次：delivery=2（粮食和弹药各2），粮食消耗2，所以粮食净变化0但毛到货是2。蓝方分类received为fuel_liters=10、spares=1、materials=1；估计运补燃油spent.fuel_liters=3，其他分类消耗0。从蓝方supply_node.stock扣2、combined_arms.depots.blue分别扣10/1/1；不从红仓扣、不凭空补仓。供给状态标为DSH估计；本QA不是运输吞吐标定。',
            '双方全部hold，无交火无到货，各消耗2粮食工作量，弹药与分类物资不变化。逐单位完整收支账，不丢失上轮到货和累计状态。']
        for turn,instruction in enumerate(instructions,1):
            previous=copy.deepcopy(before);_,rev=revision(sid)
            if turn<=committed:current=json.load(open(root/('narrative-turn'+str(turn)+'.json')))
            else:
                current=call('POST',f'/api/sessions/{sid}/next',{**rev,'batch_id':uuid.uuid4().hex,'instruction':instruction})
                save('narrative-turn'+str(turn),current)
            before=current['war_state']
            check(before['dsh_execution']['resource_ledger_version']=='dsh-resource-ledger-1' and not before.get('afsim'),
                'DSH turn '+str(turn)+' returns checked estimated accounts without AFSIM')
            for team in ('red','blue'):
                for unit in before[team+'_units']:
                    old=next(u for u in previous[team+'_units'] if u['name']==unit['name'])
                    receipt=next(r for r in before['mission']['ledger'] if r['unit']==unit['name'])
                    assert unit['logistics']['food']==old['logistics']['food']+receipt['delivery']-receipt['food_spent']
                    assert unit['logistics']['ammo']==old['logistics']['ammo']+receipt['delivery']-receipt['ammo_spent']
                    assert receipt['food_spent']==(4 if turn==1 else 2)
            check(all(u['personnel']['casualties']==0 for team in ('red','blue') for u in before[team+'_units']),
                'DSH turn '+str(turn)+' does not invent casualty quotas')
            if turn==3:
                blue=before['blue_units'][0];receipt=next(r for r in before['mission']['ledger'] if r['unit']==blue['name'])
                check(receipt['delivery']==2 and blue['logistics']['food']==previous['blue_units'][0]['logistics']['food'],
                    'real DSH distinguishes positive gross delivery from zero net food change')
                check(before['combined_arms']['depots']['blue']['fuel_liters']==previous['combined_arms']['depots']['blue']['fuel_liters']-10,
                    'real DSH classified arrivals debit the correct depot')
        check(before['current_time']=='1951-10-05 06:00','four real DSH turns preserve the exact 30-minute clock')
        main=copy.deepcopy(before);first=call('GET',f'/api/sessions/{sid}/export')['session']['trajectory'][0]
        alternate=call('POST',f'/api/sessions/{sid}/counterfactual',{'turn':1,'mode':'mission',
            'orders':[{'unit':o['unit'],'action':'hold'} for o in first['after']['mission']['last_orders']]})
        save('dsh-counterfactual',alternate)
        check(alternate['read_only'] and alternate['alternative']['dsh_execution']['resource_ledger_version']=='dsh-resource-ledger-1',
            'real DSH readonly intervention uses the same resource contract')
        check(world(sid)==main,'counterfactual never changes the authoritative model world')
        result.update(passed=True,sessions=sessions)
    except Exception as exc:
        result['error']=str(exc);raise
    finally:save('live-results',result)


if __name__=='__main__':main()
