async page=>{
 const API='http://127.0.0.1:19118',checks=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 const entry=(await get('/sessions')).sessions.find(s=>s.scenario.startsWith('原生过程预览终验 narrative cancel；'));
 if(!entry)throw Error('Use the owned final-source hold case');
 const base='/sessions/'+entry.session_id,before=await get(base),commands=await get(base+'/commands'),target=before.turn_count+1;
 check(before.turn_count<3,'The cancellation probe retains its existing active checkpoint');
 check(before.settings.persist_roles===true,'The cancellation probe uses a persistent DSH role session');
 await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19118'};localStorage.setItem('gentactix-session',id);},entry.session_id);
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 let responseReceived=false;
 const pending=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000}).then(r=>{responseReceived=true;return r;});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();
 await page.getByRole('button',{name:'取消',exact:true}).waitFor({state:'visible'});
 await page.screenshot({path:'.cache/qa/turn-settlement-2026-11-01/http/cancel-waiting-1440.png'});
 const deadline=Date.now()+900000;let progress,boundary;
 while(Date.now()<deadline){
  progress=await get(base+'/progress');
  const response=await page.request.get(API+'/qa/preview-boundary/'+entry.session_id);if(!response.ok())throw Error(await response.text());
  boundary=(await response.json()).marker;
  if(progress.active&&boundary?.operation_id===progress.operation_id)break;
  // SDK startup can precede active_observer creation. An initially inactive
  // progress endpoint is not evidence that the still-pending request finished.
  if(!progress.active&&responseReceived)throw Error('The generation completed before the preview-boundary cancellation probe');
  await page.waitForTimeout(200);
 }
 check(progress?.active&&boundary?.operation_id===progress.operation_id,'The actual Native bridge acknowledged a successful preview before cancellation');
 const cancel=page.waitForResponse(r=>r.url()===API+'/api'+base+'/cancel'&&r.request().method()==='POST');
 const started=Date.now();await page.getByRole('button',{name:'取消',exact:true}).click();
 const cancelled=await(await cancel).json(),response=await pending;
 check(response.status()===409,'The cancelled effect operation returns a noncommitted 409');
 check(cancelled.runtime.some(r=>r.ok),'Native cancellation is acknowledged by the DSH runtime');
 const after=await get(base);
 check(JSON.stringify(after.war_state)===JSON.stringify(before.war_state)&&JSON.stringify(after.history)===JSON.stringify(before.history),'Cancellation preserves physical world and report history');
 check(JSON.stringify(await get(base+'/commands'))===JSON.stringify(commands),'Cancellation does not consume or duplicate the command queue');
 const exported=await get(base+'/export'),failed=exported.failed_operations.at(-1);
 check(failed?.cancelled&&failed.operation_id===progress.operation_id,'The cancelled operation retains its own failure evidence');
 const events=failed.runs.flatMap(r=>r.events);
 check(boundary.readonly&&boundary.evidence==='actual_native_tool_bridge_callback','The observed successful read-only candidate still does not commit after cancellation');
 check(!(await get(base+'/progress')).active,'Cancelled progress is cleared');
 const cancelMs=Date.now()-started;
 const retry=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();const done=await retry;if(!done.ok())throw Error(await done.text());
 const restored=await done.json();check(restored.turn_count===target,'Retry commits only the previously uncommitted round');
 const old=Object.fromEntries([...before.war_state.red_units,...before.war_state.blue_units].map(u=>[u.name,u]));
 check([...restored.war_state.red_units,...restored.war_state.blue_units].every(u=>u.logistics.food===old[u.name].logistics.food-2&&u.logistics.ammo===old[u.name].logistics.ammo),'Retry consumes food once with no duplicate resource expenditure');
 await page.screenshot({path:'.cache/qa/turn-settlement-2026-11-01/http/cancel-recovered-1440.png'});
 return {passed:true,checks,session_id:entry.session_id,turn:target,cancel_ms:cancelMs,actual_model:true,api_mocks:false,qa_marker_instrumentation:true,
  interrupted_preview_in_native_events:events.some(e=>e.type==='tool/call'&&e.name==='preview_turn_effects'),scope:'Real preview-boundary cancellation and retry, not historical combat acceptance'};
}
