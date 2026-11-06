async page => {
  const API='http://127.0.0.1:19122',OUT='.cache/qa/dsh-output-recovery-2026-11-01',checks=[],samples=[],errors=[];
  const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
  const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
  const entry=(await get('/sessions')).sessions.find(s=>s.scenario.startsWith('单位参与状态验收 ui-recovery-fixed；'));
  if(!entry)throw Error('Missing retained actual T+2 QA checkpoint');
  const base='/sessions/'+entry.session_id,initial=await get(base);
  check(initial.turn_count===2,'Continue unchanged T+2 after retained bounded-retry failure');
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19122'};localStorage.setItem('gentactix-session',id);},entry.session_id);
  await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  const units=w=>[...w.red_units,...w.blue_units];
  function account(before,after,label){
    const old=Object.fromEntries(units(before.war_state).map(u=>[u.name,u]));
    check(after.turn_count===before.turn_count+1,label+' commits one round');
    check(after.war_state.simulation_clock.elapsed_seconds===before.war_state.simulation_clock.elapsed_seconds+1800,label+' advances only30 minutes');
    check(units(after.war_state).length===6&&units(after.war_state).every(u=>['committed','current','casualties','noncombat_losses'].every(k=>u.personnel[k]===old[u.name].personnel[k])),label+' preserves six personnel accounts');
    check(units(after.war_state).every(u=>u.logistics.food===old[u.name].logistics.food-2&&u.logistics.ammo===old[u.name].logistics.ammo),label+' charges food once, no ammunition');
    check(after.engine_meta.json_recoveries===0,label+' needs no free-final JSON recovery');
    check(!after.war_state.afsim,label+' does not substitute an AFSIM effect');
  }
  async function start(){
    let done=false;const begun=Date.now();
    const pending=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000}).then(r=>{done=true;return r;});
    await page.getByRole('button',{name:'推进一轮',exact:true}).click();
    await page.getByRole('button',{name:'取消',exact:true}).waitFor();
    return {pending,isDone:()=>done,begun};
  }
  async function accepted(before,run,label){
    const r=await run.pending;if(!r.ok())throw Error(await r.text());const after=await r.json();account(before,after,label);
    const trace=(await get(base+'/export')).trajectory.at(-1),proof=trace.guards.report.preview;
    check(proof.report_source==='dsh_native_report_tool',label+' uses a verified Native report tool');
    check(trace.runs.some(run=>run.events.some(e=>e.type==='tool/call'&&e.name==='submit_turn_report')),label+' retains the actual Native report call');
    check(trace.runs.every(r=>r.finish_reason==='completed'),label+' runtime completed before commit');
    samples.push({label,turn:after.turn_count,seconds:(Date.now()-run.begun)/1000,meta:after.engine_meta,proof});return after;
  }
  let before=initial,run=await start(),after=await accepted(before,run,'Structured report');
  before=after;
  const armed=await page.request.post(API+'/qa/native-final-fault/'+entry.session_id);if(!armed.ok())throw Error(await armed.text());
  run=await start();after=await accepted(before,run,'Corrupted free final');
  let exp=await get(base+'/export');
  check(exp.trajectory.at(-1).runs.some(r=>r.qa_final_text_fault==='qa_corrupt_free_final_after_native_report'),'QA corruption is explicitly disclosed, while report proposal is unchanged');
  before=after;const queue=await get(base+'/commands');run=await start();
  let progress,marker;const end=Date.now()+900000;
  while(Date.now()<end){
    progress=await get(base+'/progress');const response=await page.request.get(API+'/qa/native-boundary/'+entry.session_id);marker=(await response.json()).marker;
    if(progress.active&&marker?.operation_id===progress.operation_id&&marker.tool==='preview_turn_effects')break;
    if(run.isDone())throw Error('Actual operation ended before preview-boundary cancellation');
    await page.waitForTimeout(200);
  }
  check(progress?.active&&marker?.operation_id===progress.operation_id,'Current actual Native preview is read-only before cancellation');
  await page.screenshot({path:OUT+'/native-report-before-cancel.png'});
  const cancel=page.waitForResponse(r=>r.url()===API+'/api'+base+'/cancel'&&r.request().method()==='POST'),began=Date.now();
  await page.getByRole('button',{name:'取消',exact:true}).click();const cancellation=await(await cancel).json(),cancelled=await run.pending;
  check(cancelled.status()===409,'Native report operation cancellation returns409');
  check(cancellation.runtime.some(r=>r.ok),'DSH runtime confirms cancellation');
  const retained=await get(base);
  check(JSON.stringify(retained.war_state)===JSON.stringify(before.war_state),'Cancel preserves current physical world');
  check(JSON.stringify(retained.history)===JSON.stringify(before.history),'Cancel appends no report');
  check(JSON.stringify(await get(base+'/commands'))===JSON.stringify(queue),'Cancel preserves confirmed orders');
  samples.push({label:'Native cancellation',turn:retained.turn_count,cancel_ms:Date.now()-began,operation_id:progress.operation_id});
  run=await start();after=await accepted(before,run,'Native retry after cancellation');
  const final=JSON.stringify(after.war_state);await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  check(JSON.stringify((await get(base)).war_state)===final,'Browser refresh retains final exact checkpoint');
  check(errors.length===0,'No page JavaScript errors');
  await page.screenshot({path:OUT+'/native-report-final-1440.png'});
  await page.setViewportSize({width:900,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Narrow workspace has no horizontal overflow');
  await page.screenshot({path:OUT+'/native-report-final-900.png'});
  return {passed:true,session_id:entry.session_id,checks,samples,actual_model:true,actual_afsim:false,api_mocks:false,
    final_text_fault_injected:true,scope:'Native structured report completion, actual cancelled preview and retry; six QA actors, not full campaign or historical calibration'};
}
