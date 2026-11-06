/** Real SDK chat, reload while running, exact operation identity and frozen time. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const attachOnly=process.argv[3]==='observe-turn';
const fullTurn=process.argv[3]==='turn'||attachOnly;
const base=process.argv[4]??'.cache/qa/operation-clock-2026-11-03',root=base+(attachOnly?'/turn-observer':fullTurn?'/turn-browser':'/live-browser');
const waitMs=Number(process.argv[5]??900000);
if(!Number.isFinite(waitMs)||waitMs<1000||waitMs>3600000)throw Error('Explicit QA wait must be1second to1hour');
if(fs.existsSync(root))throw Error('Preserve previous evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(base+(fullTurn?'/turn-case.json':'/live-case.json'),'utf8')),sid=info.session_id;
const actorCount=info.actor_count??22,nativeCount=info.native_decision_count??2,stepSeconds=info.step_seconds??3600;
const api=info.api+'/api/sessions/'+sid;
const json=async path=>{const response=await fetch(api+path);if(!response.ok)throw Error('HTTP '+response.status);return response.json();};
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],posts=[],checks=[];
const check=(v,text)=>{if(!v)throw Error(text);checks.push(text);};
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid);},{api:info.api,sid});
const seconds=text=>text==='--:--'?null:text.split(':').map(Number).reduce((a,b)=>a*60+b,0);
let initial;
try{
 const health=await(await fetch(info.api+'/api/health')).json();check(health.runtime?.enabled,'actual Native runtime enabled');
 const priorProgress=await json('/progress');
 if(attachOnly&&!priorProgress.active)throw Error('The existing operation is no longer active; do not restart');
 if(!attachOnly&&priorProgress.active)throw Error('Another operation is already active; do not duplicate it');
 const previousId=priorProgress.last_operation?.operation_id;
 const before=(await json('/export')).session;fs.writeFileSync(root+'/before.json',JSON.stringify(before));
 await page.goto(info.ui);
 const workbench=page.getByTestId('map-workbench'),savedTab=page.getByRole('tab',{name:/已保存战局/});
 await Promise.race([workbench.waitFor(),savedTab.waitFor()]);
 if(!await workbench.isVisible()){
  await savedTab.click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
 }
 await workbench.waitFor();
 if(fullTurn){check(before.turn_count===info.turn-1,'correct retained initial turn');if(!attachOnly)await page.getByRole('button',{name:'推进一轮',exact:true}).click();}
 else{
 await page.getByRole('tab',{name:'璇玑问答',exact:true}).click();
 const input=page.getByPlaceholder(/向总参谋长璇玑提问/);
 await input.fill('只读核对当前战局：请先用get_afsim_observation读取一页部队详情，再用get_campaign_objectives读取当前目标；用不超过200字说明双方当前任务和一项不确定性。不下令，不改变战局，不声称历史已标定。');
 await page.getByRole('button',{name:'发送',exact:true}).click();
 }
 const deadline=Date.now()+120000;
 while(Date.now()<deadline){
  const value=await json('/progress');
  if(value.active&&value.progress.wall_elapsed_ms>=(fullTurn?12000:2000)){initial=value;break;}
  if(value.last_operation?.label===(fullTurn?'推演 T+'+info.turn:'璇玑问答')&&!value.active
    &&(attachOnly?value.last_operation.operation_id===priorProgress.operation_id:value.last_operation.operation_id!==previousId))throw Error('Finished before reload window; preserve evidence');
  await page.waitForTimeout(250);
 }
 check(!!initial,'real server operation observed before reload');
 const firstElapsed=initial.progress.wall_elapsed_ms;
 const firstId=initial.operation_id,startedAt=initial.progress.started_at_ms;
 fs.writeFileSync(root+'/before-reload-progress.json',JSON.stringify(initial,null,2));
 await page.reload();await page.getByTestId('map-workbench').waitFor({timeout:60000});
 await page.waitForFunction(()=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-clock-source')==='server');
 const recovered=await json('/progress');
 check(recovered.active,'reload completed while same real operation still active');
 check(recovered.operation_id===firstId&&recovered.progress.started_at_ms===startedAt,'operation identity and server start preserved');
 const shown=seconds(await page.getByTestId('operation-elapsed').innerText());
 check(shown>=Math.floor(firstElapsed/1000)-1,'real reload does not reset elapsed');
 check(Math.abs(shown-Math.floor(recovered.progress.wall_elapsed_ms/1000))<=2,'browser elapsed agrees with server within polling delay');
 check(await page.locator('.advance-button').isDisabled(),'duplicate advance blocked during real chat');
 await page.screenshot({path:root+'/recovered-running-1440.png'});
 console.log('REAL_SDK_RELOAD_VERIFIED',sid,firstId,shown);
 let terminal;const end=Date.now()+waitMs;
 while(Date.now()<end){const value=await json('/progress');if(!value.active&&value.last_operation?.operation_id===firstId){terminal=value;break;}await page.waitForTimeout(500);}
 check(!!terminal?.last_operation,'same actual operation reached a recorded outcome');
 const outcome=terminal.last_operation.outcome;
 await page.waitForFunction(value=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-state')===value,outcome,{timeout:10000});
 const text=await page.getByTestId('operation-elapsed').innerText();
 check(seconds(text)===Math.floor(terminal.last_operation.wall_elapsed_ms/1000),'terminal duration comes from persisted server fact');
 await page.waitForTimeout(1000);check(await page.getByTestId('operation-elapsed').innerText()===text,'actual terminal duration freezes');
 const after=(await json('/export')).session;fs.writeFileSync(root+'/after.json',JSON.stringify(after));
 if(fullTurn){
  check(outcome==='success','actual physical turn accepted');
  check(after.turn_count===info.turn,'physical turn committed exactly once');
  check(after.war_state.simulation_clock.elapsed_seconds-before.war_state.simulation_clock.elapsed_seconds===stepSeconds,'historical clock advances exactly'+stepSeconds+'seconds');
  const units=[...after.war_state.red_units,...after.war_state.blue_units];
  const old=[...before.war_state.red_units,...before.war_state.blue_units];
  check(units.length===actorCount&&units.every(u=>old.some(v=>v.historical_unit_id===u.historical_unit_id)),'all'+actorCount+' actor identities retained');
  const trace=after.trajectory.at(-1),decisions=trace.decisions.filter(d=>d.source==='native_unit_agent');
  check(decisions.length===nativeCount&&decisions.every(d=>d.proposal?.source==='dsh_native_unit_order_tool'),nativeCount+' native structured unit decisions retained');
  check(after.command_state.receipts.filter(r=>r.turn===info.turn).length===actorCount,'all'+actorCount+' command receipts present');
  check(trace.guards.report.status==='screened','committed report passed existing claim screen');
 }else{
  for(const key of ['war_state','turn_count','history','trajectory','command_state','force_organization','decision_log'])
   check(JSON.stringify(before[key])===JSON.stringify(after[key]),'readonly chat preserves '+key);
  check(after.chat_messages.length===before.chat_messages.length+2,'one user message and one actual answer stored');
 }
 check(after.engine_last_meta.operation_id===firstId&&after.engine_last_meta.trace_runs>0,'actual SDK metadata matches recovered operation');
 check(attachOnly?posts.length===0:posts.filter(x=>x.endsWith(fullTurn?'/next':'/chat')).length===1&&posts.length===1,'reload never duplicates actual request');
 await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/completed-900.png'});
 check(errors.length===0,'no application errors');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,actual_model:true,physical_turn:fullTurn,attached_to_existing_operation:attachOnly,turn:fullTurn?info.turn:undefined,session_id:sid,operation_id:firstId,checks,count:checks.length,
  first_elapsed_ms:firstElapsed,recovered_elapsed_ms:recovered.progress.wall_elapsed_ms,terminal:terminal.last_operation,posts,errors,
  scope:fullTurn?'Actual normal Native physical turn and refresh, not full battle or historical calibration':'Actual Native readonly chat; refresh during operation, one request and retained world; no battle/history/answer-semantic acceptance'},null,2));
 console.log('PASS',checks.length,'actualNative clock/recovery checks');
}catch(error){
 const response=await json('/export').catch(()=>null);if(response&&!fs.existsSync(root+'/after.json'))fs.writeFileSync(root+'/after.json',JSON.stringify(response.session));
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,posts,errors,session_id:sid,expected_turn:fullTurn?info.turn:undefined,clock_recovery_verified:checks.includes('operation identity and server start preserved'),physical_turn:fullTurn},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
