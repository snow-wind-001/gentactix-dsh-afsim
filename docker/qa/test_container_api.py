"""Actual HTTP deployment checks against isolated fresh Docker volumes only."""
import argparse,json,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
p=argparse.ArgumentParser();p.add_argument('--port',type=int,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--expect-afsim',action='store_true');a=p.parse_args();base=f'http://127.0.0.1:{a.port}';checks=[]
def call(path,body=None,headers=None,method=None):
 data=None if body is None else json.dumps(body).encode();h={'Content-Type':'application/json',**(headers or {})}
 try:
  with urlopen(Request(base+path,data=data,headers=h,method=method),timeout=30) as r:return r.status,r.read()
 except HTTPError as e:return e.code,e.read()
def check(name,condition):
 checks.append({'name':name,'passed':bool(condition)});assert condition,name
for attempt in range(90):
 try:
  status,body=call('/api/health');health=json.loads(body)
  if status==200:break
 except Exception:time.sleep(2)
else:raise SystemExit('health timeout')
check('api_health',health['status']=='ok')
check('afsim_availability',health['afsim']['available']==a.expect_afsim)
check('source_loaded_matches_disk',health['build']['loaded_revision']==health['build']['disk_revision'] and not health['build']['restart_required'])
status,body=call('/');check('vue_index',status==200 and b'container-config.js' in body and b'<div id="app"></div>'in body)
status,body=call('/container-config.js');check('same_origin_api_configuration',status==200 and b'window.location.origin'in body)
status,body=call('/api/battles');battles=json.loads(body)['battles'];check('battle_catalog_nonempty',status==200 and len(battles)>=45)
status,body=call('/api/llm/config');config=json.loads(body);check('default_medium_reasoning',config['role_policies']['engine']['reasoning_effort']=='medium');check('output_context_budgets',config['max_tokens']==65536 and config['context_window']==262144)
check('foreign_host_rejected',call('/api/health',headers={'Host':'attacker.example'})[0]==403)
check('foreign_origin_rejected',call('/api/health',headers={'Origin':'https://attacker.example'})[0]==403)
status,body=call('/api/sessions');check('fresh_volume_has_no_user_saved_games',status==200 and not json.loads(body)['sessions'])
status,body=call('/api/sessions',{'scenario':'Docker delivery persistence validation only','time_step':'15分钟'});identity=json.loads(body)['session_id'];check('isolated_checkpoint_create',status==200)
new={k:config[k]for k in ('base_url','model','max_tokens','context_window','timeout_seconds','role_policies','max_steps','max_tool_calls')};new.update(base_url='http://127.0.0.1:9/v1',model='docker-delivery-validation',api_key='delivery-canary-only-not-a-real-credential')
status,body=call('/api/llm/config',new,method='PUT');check('encrypted_config_api_save',status==200);check('api_never_returns_test_secret',b'delivery-canary-only-not-a-real-credential'not in body)
a.out.write_text(json.dumps({'passed':all(x['passed']for x in checks),'checks':checks,'session_id':identity,'catalog_count':len(battles),'source_revision':health['build']['loaded_revision']},ensure_ascii=False,indent=2))
print(a.out.read_text())
