async page => {
  const API='http://127.0.0.1:19122',OUT='.cache/qa/dsh-output-recovery-2026-11-01',checks=[],samples=[];
  const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
  const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
  const entry=(await get('/sessions')).sessions.find(s=>s.scenario.startsWith('单位参与状态验收 ui-recovery-fixed；'));
  if(!entry)throw Error('Missing retained recovery checkpoint');
  const base='/sessions/'+entry.session_id,before=await get(base),queue=await get(base+'/commands'),exported=await get(base+'/export');
  check(before.turn_count===2,'Continue from the actual recovered T+2 checkpoint, without replacing the earlier failed QA attempts');
  const first=exported.trajectory.find(r=>r.turn===1),second=exported.trajectory.find(r=>r.turn===2);
  check(first?.before&&first.after&&second?.before&&second.after,'Both actual completed rounds retain their world transitions');
  check(JSON.stringify(first.after)===JSON.stringify(second.before),'The normal and recovered rounds share one continuous world');
  const units=w=>[...w.red_units,...w.blue_units];
  for(const record of [first,second]){
    const previous=Object.fromEntries(units(record.before).map(u=>[u.name,u]));
    check(record.after.simulation_clock.elapsed_seconds===record.before.simulation_clock.elapsed_seconds+1800,'Each retained round advances exactly 30 minutes');
    check(units(record.after).every(u=>['committed','current','casualties','noncombat_losses'].every(k=>u.personnel[k]===previous[u.name].personnel[k])),'Retained personnel balances stay exact');
    check(units(record.after).every(u=>u.logistics.food===previous[u.name].logistics.food-2&&u.logistics.ammo===previous[u.name].logistics.ammo),'Retained food is charged once and ammunition is unchanged');
  }
  check(second.runs.some(r=>r.rejection==='invalid_final_json'&&r.accepted===false),'The actual rejected final remains recorded separately from the accepted result');
  check(before.engine_meta.json_recoveries===1,'Natural invalid JSON recovered exactly once');
  const fault=await page.request.get(API+'/qa/final-output-fault/'+entry.session_id),faultValue=await fault.json();
  check(faultValue.attempts.at(-1)?.natural_invalid_json===true&&!faultValue.attempts.at(-1)?.injected,'The earlier fault was spontaneous, with no injected corruption');
  await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19122'};localStorage.setItem('gentactix-session',id);},entry.session_id);
  await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  const armed=await page.request.post(API+'/qa/final-output-fault/'+entry.session_id);if(!armed.ok())throw Error(await armed.text());
  let received=false;
  const pending=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000}).then(r=>{received=true;return r;});
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();
  const deadline=Date.now()+900000;let progress;
  while(Date.now()<deadline){
    progress=await get(base+'/progress');
    if(progress.active&&progress.progress.phase==='json_output_recovery')break;
    if(received)throw Error('Operation ended before cancellation in recovery');
    await page.waitForTimeout(300);
  }
  check(progress?.active&&progress.progress.phase==='json_output_recovery','Actual Native operation reached final-output recovery');
  await page.getByTestId('operation-status').filter({hasText:'正在恢复模型输出'}).waitFor();
  check(await page.getByTestId('operation-progress').getAttribute('data-stage')==='waiting','Waiting colour is visible during recovery');
  await page.screenshot({path:OUT+'/cancel-recovery-waiting-1440.png'});
  const cancel=page.waitForResponse(r=>r.url()===API+'/api'+base+'/cancel'&&r.request().method()==='POST');
  const began=Date.now();await page.getByRole('button',{name:'取消',exact:true}).click();
  const cancelled=await(await cancel).json(),response=await pending;
  check(response.status()===409,'Cancelled recovery returns noncommitted 409');
  check(cancelled.runtime.some(r=>r.ok),'DSH Native cancellation is acknowledged');
  const retained=await get(base);
  check(JSON.stringify(retained.war_state)===JSON.stringify(before.war_state),'Cancelled recovery does not alter the physical world');
  check(JSON.stringify(retained.history)===JSON.stringify(before.history),'Cancelled recovery does not append a report');
  check(JSON.stringify(await get(base+'/commands'))===JSON.stringify(queue),'Cancelled recovery does not consume pending commands');
  const failures=(await get(base+'/export')).failed_operations;
  check(failures.at(-1)?.cancelled&&failures.at(-1)?.operation_id===progress.operation_id,'Cancellation keeps its own failure trajectory');
  samples.push({kind:'cancel-in-recovery',cancel_ms:Date.now()-began,operation_id:progress.operation_id});
  const retry=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000});
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();const done=await retry;if(!done.ok())throw Error(await done.text());
  const after=await done.json(),previous=Object.fromEntries(units(before.war_state).map(u=>[u.name,u]));
  check(after.turn_count===3,'Retry commits only the previously cancelled round');
  check(after.war_state.simulation_clock.elapsed_seconds===before.war_state.simulation_clock.elapsed_seconds+1800,'Retry advances physical time once');
  check(units(after.war_state).every(u=>u.logistics.food===previous[u.name].logistics.food-2&&u.logistics.ammo===previous[u.name].logistics.ammo),'Retry charges resources once');
  const final=JSON.stringify(after.war_state);await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  check(JSON.stringify((await get(base)).war_state)===final,'Browser refresh retains the committed checkpoint');
  await page.screenshot({path:OUT+'/recovered-final-1440.png'});
  return {passed:true,session_id:entry.session_id,checks,samples,turn:3,actual_model:true,actual_afsim:false,api_mocks:false,
    qa_fault_evidence:(await(await page.request.get(API+'/qa/final-output-fault/'+entry.session_id)).json()).attempts,
    scope:'Real natural final-JSON recovery and later cancellation/retry from retained checkpoint; prior QA helper/assertion failures retained; not uninterrupted or full historical acceptance'};
}
