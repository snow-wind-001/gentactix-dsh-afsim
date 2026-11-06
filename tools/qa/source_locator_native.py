"""Real readonly Native lookup of current editorial evidence; --live required.

No physical simulation, historical calibration or frozen-profile migration.
All writable runtime directories are isolated; saved model settings are read.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time

ROOT = Path('.cache/qa/long-march-source-admission-2026-11-01')


def run():
    folder = ROOT/'native'/str(time.time_ns())
    folder.mkdir(parents=True)
    for key, suffix in [('SESSION_DIR','sessions'), ('TRACE_DIR','traces'), ('DSH_HOME','dsh-home'),
                        ('DSH_WORKSPACE','workspace'), ('ROLE_INDEX','roles.json')]:
        os.environ['GENTACTIX_'+key] = str((folder/suffix).resolve())
    from backend import harness_engine as h, runtime_bridge, afsim_state
    from backend.main import _native_tool_dispatch
    from gentactix import history_replay
    calls = []
    result = dict(passed=False, actual_model=True, actual_afsim=False, cases=[],
                  scope='Current editorial source lookup through existing Native tool; no physical campaign or unrestricted interpretation acceptance')

    def save():
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def dispatch(context, payload):
        response = _native_tool_dispatch(context,payload)
        calls.append(dict(tool=payload.get('tool'),args=payload.get('args'),response=response))
        return response

    runtime_bridge.register_dispatcher(dispatch)
    observer = h.RunObserver('当前史料逐项定位核查')
    cases = [
        ('湘江战役','红军长征-湘江战役-1934.11.25至1934.12.01',
         '数字来源定位 红5师 新圩 两团参战兵力',
         '红5师两团合计参战兵力记载多少、限定词是什么、哪个来源？能否平均分给下级团？'
         '缺载数值必须为null，不填0。qualifier只填余人、约人、人、未核得之一，解释不放入该字段。'
         '只返回JSON {"people":整数或null,"qualifier":"限定词枚举","source_id":"来源ID","distribute_to_regiments":布尔值,"original_archive_examined":布尔值}。',
         dict(people=3000,qualifier='余人',source_id='S04',distribute_to_regiments=False,original_archive_examined=False)),
        ('强渡乌江','红军长征-强渡乌江-1935.01.01至1935.01.06',
         '数字来源定位 回龙场 遇难',
         '回龙场所载遇难人数多少、哪个来源？能否作为全部渡口战役阵亡总数？全部渡口伤亡合计是否已核得？'
         '缺载数值必须为null，不填0。只返回JSON {"people":整数或null,"source_id":"来源ID","whole_campaign_killed":布尔值,"all_crossings_casualty_total_known":布尔值}。',
         dict(people=8,source_id='S05',whole_campaign_killed=False,all_crossings_casualty_total_known=False)),
    ]
    try:
        for index, (label,battle,query,question,expected) in enumerate(cases):
            pinned = history_replay.pin(battle)
            session = dict(id='source-locator-native-'+str(index),war_state=history_replay.frame_pinned(pinned,0),
                turn_count=0,battle_choice=battle,execution_backend='narrative',product_mode='analysis',
                simulation_mode='replay',use_rag=True,history=[])
            before = copy.deepcopy(session);start = len(calls);began = time.monotonic()
            prompt = ('请实际调用已注册的retrieve_history，query='+json.dumps(query,ensure_ascii=False)+'。'
                '只依工具返回的当前参考资料回答，不调用修改或推演工具，不把参考数字写入冻结战局。'
                '来源定位齐全不等于查阅过原始档案。'+question)
            reply = h._run_brain(prompt,None,role='chat',observer=observer,
                                 native_context=afsim_state.operation_context(session))
            answer = h.parse_json_object(reply.final_response)
            actual = calls[start:]
            row = dict(label=label,answer=answer,expected=expected,seconds=round(time.monotonic()-began,3),
                       finish_reason=reply.finish_reason,world_unchanged=session==before,calls=actual)
            result['cases'].append(row);save()
            assert reply.finish_reason=='completed' and answer==expected,label+': public answer differs; see retained result.json'
            assert session==before,'Readonly lookup changed a source frame'
            assert any(c['tool']=='retrieve_history' and c['response'].get('ok') and
                       any(p['section']=='数字来源定位' for p in c['response'].get('passages',[])) for c in actual)
            needles = ('3000余人','不分摊','S04') if index==0 else ('8人','回龙场','S05')
            assert any(all(word in p['text'] for word in needles) for c in actual
                       for p in c['response'].get('passages',[]) if p['section']=='数字来源定位'), 'Requested evidence was absent; a correct guess is insufficient'
            print('PASS real Native source lookup',label,flush=True)
        result.update(passed=True,meta=observer.meta())
    except Exception as exc:
        result['error']=str(exc)
        raise
    finally:
        save();h.close_harness();print('Evidence:',folder,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required to use the configured real model')
    run()
