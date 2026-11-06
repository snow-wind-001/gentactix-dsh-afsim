async page => {
  const API='http://127.0.0.1:19122',OUT='.cache/qa/dsh-output-recovery-2026-11-01',checks=[],samples=[],errors=[];
  const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
  const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
  const faults=async sid=>{const r=await page.request.get(API+'/qa/final-output-fault/'+sid);if(!r.ok())throw Error(await r.text());return r.json();};
  const arm=async sid=>{const r=await page.request.post(API+'/qa/final-output-fault/'+sid);if(!r.ok())throw Error(await r.text());};
  const entry=(await get('/sessions')).sessions.find(s=>s.scenario.startsWith('单位参与状态验收 ui-recovery-fixed；'));
  if(!entry)throw Error('Prepare the isolated ui-recovery case first');
  const base='/sessions/'+entry.session_id,initial=await get(base);
  check([0,1].includes(initial.turn_count),'Fresh world or its first verified normal checkpoint; no previous result is overwritten');
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19122'};localStorage.setItem('gentactix-session',id);},entry.session_id);
  await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();

  function accounts(before,after,label){
    const old=Object.fromEntries([...before.war_state.red_units,...before.war_state.blue_units].map(u=>[u.name,u]));
    const units=[...after.war_state.red_units,...after.war_state.blue_units];
    check(after.turn_count===before.turn_count+1,label+' commits exactly one round');
    check(after.war_state.simulation_clock.elapsed_seconds===before.war_state.simulation_clock.elapsed_seconds+1800,label+' advances physical time exactly 30 minutes');
    check(units.length===6&&units.every(u=>['committed','current','casualties','noncombat_losses'].every(k=>u.personnel[k]===old[u.name].personnel[k])
      &&u.personnel.source===old[u.name].personnel.source),label+' preserves all six personnel accounts and their source');
    check(units.every(u=>u.equipment.every(e=>{const previous=old[u.name].equipment.find(p=>p.category===e.category);return previous&&['committed','operational','damaged','destroyed'].every(k=>e[k]===previous[k]);})),label+' preserves classified equipment accounts');
    check(units.every(u=>u.logistics.food===old[u.name].logistics.food-2&&u.logistics.ammo===old[u.name].logistics.ammo),label+' consumes food once and no ammunition');
    check(!after.war_state.afsim,label+' has no substituted AFSIM effect receipt');
  }

  async function start(){
    let done=false;
    const pending=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000}).then(r=>{done=true;return r;});
    const begun=Date.now();await page.getByRole('button',{name:'推进一轮',exact:true}).click();
    await page.getByTestId('operation-progress').waitFor({state:'visible'});
    check(await page.getByRole('button',{name:'取消',exact:true}).isEnabled(),'Cancel remains available while the model runs');
    return {pending,isDone:()=>done,begun};
  }

  async function recoveryBoundary(run){
    const end=Date.now()+900000;let state;
    while(Date.now()<end){
      state=await get(base+'/progress');
      if(state.active&&state.progress.phase==='json_output_recovery')break;
      if(run.isDone())throw Error('Operation finished before the final-output recovery boundary');
      await page.waitForTimeout(400);
    }
    check(state?.active&&state.progress.phase==='json_output_recovery','Actual operation enters bounded final-JSON recovery');
    return state;
  }

  // First normal actual-model round, without QA output alteration.
  let before=await get(base),run,response,after;
  if(before.turn_count===0){
    run=await start();response=await run.pending;if(!response.ok())throw Error(await response.text());
    after=await response.json();accounts(before,after,'Normal Native process');
    samples.push({kind:'normal',turn:after.turn_count,seconds:(Date.now()-run.begun)/1000,meta:after.engine_meta});
  }else{
    const saved=await get(base+'/export'),normal=saved.trajectory.find(r=>r.turn===1);
    check(normal?.before&&normal.after,'The earlier normal round has durable input and output evidence');
    accounts({turn_count:0,war_state:normal.before},before,'Retained normal Native process');after=before;
    samples.push({kind:'normal-retained-after-qa-helper-correction',turn:1,meta:before.engine_meta});
  }

  // Explicit application-boundary corruption after a real successful preview.
  before=after;const beforeQueue=await get(base+'/commands');await arm(entry.session_id);run=await start();
  await recoveryBoundary(run);
  await page.getByTestId('operation-status').filter({hasText:'正在恢复模型输出'}).waitFor();
  check(await page.getByTestId('operation-progress').getAttribute('data-stage')==='waiting','Recovery has a waiting colour instead of success');
  const pendingWorld=await get(base);
  check(JSON.stringify(pendingWorld.war_state)===JSON.stringify(before.war_state),'Successful preview and malformed final have not committed a world');
  const during=await get(base+'/commands');
  check(JSON.stringify(during.orders)===JSON.stringify(beforeQueue.orders),'Recovery retains confirmed commands');
  await page.screenshot({path:OUT+'/recovery-waiting-1440.png'});
  await page.setViewportSize({width:900,height:1000});
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Narrow recovery layout has no horizontal overflow');
  check((await page.getByTestId('operation-progress').getAttribute('aria-valuetext')).includes('正在恢复模型输出'),'Narrow recovery state remains accessible');
  await page.screenshot({path:OUT+'/recovery-waiting-900.png'});await page.setViewportSize({width:1440,height:1000});
  response=await run.pending;if(!response.ok())throw Error(await response.text());after=await response.json();
  accounts(before,after,'Recovered Native process');check(after.engine_meta.json_recoveries===1,'Exactly one final-JSON recovery is recorded');
  let exportValue=await get(base+'/export'),trace=exportValue.trajectory.at(-1);
  check(trace.runs.some(r=>r.accepted===false&&r.rejection==='invalid_final_json'),'Rejected completed attempt is retained in the public operation trajectory');
  check(trace.runs.filter(r=>r.finish_reason==='completed').length>=2,'Recovery uses actual Native model calls');
  const faultLog=await faults(entry.session_id);
  const observed=faultLog.attempts.at(-1);
  check(observed?.injected===true||observed?.natural_invalid_json===true,'Explicit QA truncation or a spontaneous invalid final is identified without conflating them');
  samples.push({kind:observed.injected?'injected-final-truncation-recovered':'natural-invalid-final-recovered',turn:after.turn_count,seconds:(Date.now()-run.begun)/1000,meta:after.engine_meta,fault:observed});

  // Cancel the actual runtime during the recovery call; then retry the same turn.
  before=after;const queuedBeforeCancel=await get(base+'/commands');await arm(entry.session_id);run=await start();
  const boundary=await recoveryBoundary(run);
  const cancelResponse=page.waitForResponse(r=>r.url()===API+'/api'+base+'/cancel'&&r.request().method()==='POST');
  const cancelStart=Date.now();await page.getByRole('button',{name:'取消',exact:true}).click();
  const cancellation=await(await cancelResponse).json();response=await run.pending;
  check(response.status()===409,'Cancellation during recovery returns a noncommitted 409');
  check(cancellation.runtime.some(r=>r.ok),'DSH Native runtime acknowledges cancellation');
  after=await get(base);check(JSON.stringify(after.war_state)===JSON.stringify(before.war_state),'Cancellation preserves the exact world');
  check(JSON.stringify(after.history)===JSON.stringify(before.history),'Cancellation adds no report');
  check(JSON.stringify(await get(base+'/commands'))===JSON.stringify(queuedBeforeCancel),'Cancellation does not consume pending orders');
  exportValue=await get(base+'/export');const failed=exportValue.failed_operations.at(-1);
  check(failed.cancelled&&failed.operation_id===boundary.operation_id,'Cancellation evidence retains the rejected and interrupted operation');
  samples.push({kind:'cancelled-during-recovery',turn:after.turn_count,cancel_ms:Date.now()-cancelStart,operation_id:boundary.operation_id});
  run=await start();response=await run.pending;if(!response.ok())throw Error(await response.text());after=await response.json();accounts(before,after,'Retry after cancellation');
  check(after.turn_count===3,'Three rounds committed despite the interrupted extra operation');
  samples.push({kind:'retry-after-cancel',turn:after.turn_count,seconds:(Date.now()-run.begun)/1000,meta:after.engine_meta});
  await page.screenshot({path:OUT+'/recovered-final-1440.png'});
  const final=JSON.stringify(after.war_state);await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  check(JSON.stringify((await get(base)).war_state)===final,'Browser refresh keeps the committed checkpoint');
  check(errors.length===0,'No page JavaScript errors');
  return {passed:true,session_id:entry.session_id,checks,samples,actual_model:true,actual_afsim:false,api_mocks:false,
    qa_output_fault_injection:(await faults(entry.session_id)).attempts.some(r=>r.injected),scope:'Native final-output recovery, cancellation, normal UI and exact ledger continuity; not full historical campaign or loss calibration'};
}
