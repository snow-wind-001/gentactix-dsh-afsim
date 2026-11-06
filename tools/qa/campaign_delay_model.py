"""Actual DSH read-only review of the completed34unit Native QA turn."""
import argparse,copy,json,os,time
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
if not args.live:parser.error('Configured model calls require --live')
base=Path('.cache/qa/scenario-resume-2026-11-01');out=base/'delay-model'/str(time.time_ns());out.mkdir(parents=True)
for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','dsh-home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json')]:os.environ['GENTACTIX_'+key]=str((out/suffix).resolve())
from backend import harness_engine as h,runtime_bridge,afsim_state
from backend.main import _native_tool_dispatch
session=json.loads((base/'post-turn-response.json').read_text());session.update(id=session['session_id'],execution_backend='afsim',battle_choice=session['war_state']['historical_initial']['definition']['battle'])
before=copy.deepcopy(session);observer=h.RunObserver('只读核对真实34单位迟滞想定');calls=[];result={'passed':False,'actual_model':True,'scope':'Read-only factual query, not causal attribution or historical calibration'}
def dispatch(context,payload):
 value=_native_tool_dispatch(context,payload);calls.append({'tool':payload.get('tool'),'args':payload.get('args'),'response':value});return value
runtime_bridge.register_dispatcher(dispatch)
try:
 prompt=('只读核对当前已提交的实际AFSIM检查点。先调用get_afsim_observation(limit=16,offset=0)，沿工具分页读取全部单位，禁止用旧对话代替当前状态。'
  '依据mission与operational_process读取目标规则和达标情况。defensive-delay-1的空间参考指标不是夺占条件。'
  '只返回JSON {"turn":已提交轮次,"elapsed_seconds":全局已过秒数,"unit_count":分页实际单位总数,'
  '"objective_policy":"实际规则版本","mission_condition":实际布尔值,"requires_town_occupation":布尔值,"full_history_accepted":false}。'
  '使用可用函数原名，不加前缀，不在正文模拟调用，不执行动作，不改配置。')
 run=h._run_brain(prompt,None,role='chat',observer=observer,native_context=afsim_state.operation_context(session))
 answer=h.parse_json_object(run.final_response)
 expected={'turn':1,'elapsed_seconds':21600,'unit_count':34,'objective_policy':'defensive-delay-1','mission_condition':False,'requires_town_occupation':False,'full_history_accepted':False}
 if answer!=expected:raise AssertionError(answer)
 if not any(c['tool']=='get_afsim_observation' for c in calls):raise AssertionError('Actual Native read missing')
 if session!=before:raise AssertionError('Read-only review changed the checkpoint')
 result.update(passed=True,answer=answer,world_unchanged=True,meta=observer.meta());print('PASS actual DSH Native34unit read and defensive objective facts',flush=True)
finally:
 result['calls']=calls;(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));(out/'runs.json').write_text(json.dumps(observer.runs,ensure_ascii=False,indent=2));h.close_harness();print('RESULT',out/'result.json',flush=True)
