"""Actual native DSH configuration and AFSIM round for sourced partial forces."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import uuid


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--port',type=int,default=19097)
    p.add_argument('--resume-session',help='Reuse a verified turn-zero QA session after a request failure; do not regenerate')
    p.add_argument('--out',type=Path,default=Path('.cache/qa/wanjialing-sources-2026-10-31/build'))
    args=p.parse_args()
    if not args.live or not 19090<=args.port<=19110:p.error('Use --live with isolated QA service')
    root=args.out;root.mkdir(parents=True,exist_ok=True)
    from tools.upgrade_wanjialing import BATTLE
    from gentactix import missions,sim_clock
    base=f'http://127.0.0.1:{args.port}'
    def call(method,path,body=None):
        req=urllib.request.Request(base+path,method=method,headers={'Content-Type':'application/json'},
            data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req,timeout=1200) as r:return json.load(r)
        except urllib.error.HTTPError as e:raise RuntimeError(str(e.code)+': '+e.read().decode()[:2200]) from e
    def save(name,value):(root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    result={'passed':False,'scope':'Sourced six execution identities plus explicit model estimates, not full historical campaign/calibration'}
    try:
        instruction=('验证万家岭1.1.0的已核局部投入，不求复现全军和全役。保留6个执行ID；4项oob_coverage余部均明确excluded_unquantified，绝不改成完整军。'
            '真实位置与兵额未知，逐单位说明独立估计；不要使用理论满编或从历史总伤亡倒分。'
            '选局部接敌教学参数，1938-10-07 00:00、30分钟、按objectives完成，planning只做参考。'
            '军师投入部在磨溪工作范围内作不同方向的估计部署，彼此接触距离约0.5至1公里，避免大距离开局长期无接触。'
            '目标用3个分方向地域，表示石堡山、长岭—张古山、第4军方向的功能性估计位置，明确不是历史坐标。'
            '须配置combined_operation，充足但有界的粮弹及分类库存，所有到场时间明确标注估计。'
            '保留1910年代装备不合适，本场是1938年徒步部队；不要编造装甲航空实际单位或史实装备数。'
            '初始各单位有步兵机动/射击能力，支援以已声明装备校验。所有人数、装备、工事、后勤和武器效能未标定。')
        if args.resume_session:
            draft=json.loads((root/'draft.json').read_text())
        else:
            draft=call('POST','/api/historical-scenarios/build',dict(battle=BATTLE,phase_id='oct7_attack',version='1.1.0',
                instruction=instruction,execution_backend='afsim',time_step='30分钟',termination_mode='objectives',force_scope='phase'))
            save('draft',draft);print('Generated and actually loaded six source-based execution units',flush=True)
        assert len(draft['parameters']['actors'])==6
        assert all(r['policy']=='excluded_unquantified' for r in draft['parameters']['oob_coverage']['remainders'].values())
        if args.resume_session:
            sid=args.resume_session;before=call('GET',f'/api/sessions/{sid}')
            assert before['turn_count']==0,'Resume requires verified turn zero'
        else:
            created=call('POST','/api/sessions',dict(scenario='万家岭1.1.0局部具名初态与会战资料链路QA；数值估计未标定',battle=BATTLE,
                product_mode='historical',simulation_mode='open',execution_backend='afsim',time_step='30分钟',
                historical_parameters=draft['parameters'],scenario_draft_id=draft['id']))
            sid=created['session_id'];before=call('POST',f'/api/sessions/{sid}/init');save('initial',before)
        result['session_id']=sid
        assert before['war_state']['historical_initial']['version']=='1.1.0'
        view=call('GET',f'/api/sessions/{sid}/commands')
        snap=call('POST',f'/api/sessions/{sid}/next',{'instruction':'先读取权威态势和全部6个可行动ID。红蓝双方均下合法行动命令：射程及资源允许时针对最近对方射击；否则选择可行接近或明确等待。保留身份和资源账，不按历史总伤亡强制结算。','batch_id':uuid.uuid4().hex,'expected_turn':view['turn'],
            **{k:view[k] for k in ('revision','world_version')}})
        save('turn1',snap);world=snap['war_state'];units=list(missions.units(world))
        assert len(units)==6 and world['current_time']==sim_clock.target(before['war_state'],'30分钟')[0]
        for _,u in units:
            a=u['personnel'];assert a['committed']==a['current']+a['casualties']+a['noncombat_losses']
            assert all(e['committed']==e['operational']+e['damaged']+e['destroyed'] for e in u['equipment'])
        result.update(passed=True,units=len(units),source_version=world['historical_initial']['version'],
            losses={team:sum(u['personnel']['casualties'] for u in world[team+'_units']) for team in ('red','blue')},
            time=world['current_time'],afsim=world.get('afsim'),construction=draft.get('construction'))
        print('PASS sourced partial-force draft, frozen version, real DSH/native round, time and resource continuity',flush=True)
    finally:
        save('result',result);print('Evidence:',root,flush=True)


if __name__=='__main__':main()
