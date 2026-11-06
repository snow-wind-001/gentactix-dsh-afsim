"""Real DSH-only six-hour process through existing Native preview/report tools."""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('--live required to call the configured model')
    root=Path('.cache/qa/supply-schedule-2026-11-01/model')/str(time.time_ns());root.mkdir(parents=True)
    for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),
                       ('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str(root.resolve()/suffix)
    from verify_supply_schedule import world
    from gentactix import missions
    from backend import dsh_simulation,runtime_bridge,harness_engine as h
    from backend.main import _native_tool_dispatch
    before=world();session={'id':'a123456789ab','war_state':before,'turn_count':0,'time_step':'6小时',
        'simulation_mode':'open','agent_mode':'native','execution_backend':'narrative','role_epoch':0}
    prior=copy.deepcopy(session);calls=[]
    def dispatch(ctx,payload):
        result=_native_tool_dispatch(ctx,payload)
        calls.append({'tool':payload.get('tool'),'result':result})
        return result
    runtime_bridge.register_dispatcher(dispatch)
    observer=h.RunObserver('真实DSH定时补给六小时过程')
    result={'passed':False,'actual_model':True,'actual_afsim':False,'scope':'Numerical QA with fixed bilateral hold orders, not history or autonomous tactical decision acceptance'}
    orders=[{'unit':u['name'],'action':'hold'} for _,u in missions.units(before)]
    rules=before['mission']['definition']['combined_rules']
    try:
        output,accepted,_=dsh_simulation.advance(session,None,observer,fixed_orders=orders,
            instruction='本次真实DSH独立过程验证，AFSIM关闭。双方3单位仅执行固定hold，不开火、不移动、不产生损失。'
                '现有仓库库存充足，敌地控半径0、陆上路线未被切断，普通保障按配置每小时4工作量粮食配送，弹药满100因此无需补弹；其他分类物资本次无需求，可全部零到货/零消耗。'
                '严格计算全部六次delivery及最后settlement。不能遗漏小时事件、用未来到货补偿先前缺粮，或照抄示例food_spent=2。'
                '情报按经过分钟老化，不把六小时当30分钟。库存及时序字段以当前输入计算，未提供的史实数字不编造。'
                '按需用get_afsim_observation读取换算和当前态势；以下只重复输入换算参数，不提供结果：'+
                json.dumps({k:rules[k] for k in ('ton_per_supply_unit','transport_tons_per_truck','cargo_mass_tons')},ensure_ascii=False)+
                '。先preview_turn_effects取得成功结算，再submit_turn_report提交本轮公开战报；最终简短确认。')
        after=output['updated_state'];missions.validate(after)
        assert session==prior and after['simulation_clock']['elapsed_seconds']==21600
        assert output.get('report_preview')
        assert len(accepted)==3 and all(o['action']=='hold' for o in accepted)
        for _,u in missions.units(after):
            assert u['logistics']=={'food':4,'ammo':100}
            assert u['personnel']['casualties']==u['personnel']['noncombat_losses']==0
        assert all(r['food_spent']==20 and r['food_received']==24 for r in after['mission']['ledger'])
        assert any(c['tool']=='preview_turn_effects' and c['result'].get('ok') for c in calls)
        assert any(c['tool']=='submit_turn_report' and c['result'].get('ok') for c in calls)
        (root/'after.json').write_text(json.dumps(after,ensure_ascii=False)+'\n')
        result.update(passed=True,world_unchanged=True,units=3,hours=6,receipt_events=21,meta=observer.meta())
        print('PASS real DSH timed ledger, native preview/report and exact gross accounts',flush=True)
    except Exception as exc:result['error']=str(exc);raise
    finally:
        result['calls']=calls
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (root/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2)+'\n')
        h.close_harness();print('Evidence:',root,flush=True)


if __name__=='__main__':main()
