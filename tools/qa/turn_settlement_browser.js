async page=>{
 const API='http://127.0.0.1:19118',checks=[],samples=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 const entry=(await get('/sessions')).sessions.find(s=>s.scenario.startsWith('单世界十阶段验收 narrative；'));
 if(!entry)throw Error('Create the isolated turn-settlement lifecycle case first');
 const base='/sessions/'+entry.session_id,before=await get(base),start=before.turn_count,target=Math.min(start+4,12);
 check(start<12,'The segment starts before the completed campaign');
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19118'};localStorage.setItem('gentactix-session',id);},entry.session_id);
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const panel=page.getByTestId('campaign-lifecycle');
 const show=async()=>{if(!await panel.isVisible())await page.getByRole('button',{name:/目标与运行/}).click();await panel.waitFor({state:'visible'});};
 await show();
 for(let turn=start+1;turn<=target;turn++){
  const response=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:900000});
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();
  check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),'Round '+turn+' disables duplicate advancement');
  const r=await response,d=await r.json();if(!r.ok())throw Error(JSON.stringify(d));
  const w=d.war_state,trace=(await get(base+'/traces/'+turn)).record,audit=trace.guards.report;
  check(d.turn_count===turn,'Round '+turn+' committed once through the UI');
  check(w.simulation_clock.elapsed_seconds===turn*1800,'Round '+turn+' advances exactly thirty minutes');
  check(w.dsh_execution?.effects_source==='dsh_model_estimate'&&!w.afsim,'Round '+turn+' uses actual DSH effects without AFSIM');
  check(audit.preview?.evidence==='dsh_public_tool_trajectory','Round '+turn+' retains a real Native preview proof');
  check(trace.runs.some(run=>run.events.some(e=>e.type==='tool/call'&&e.name==='preview_turn_effects')),'Round '+turn+' has a Native tool call rather than a fixture');
  const units=[...w.red_units,...w.blue_units];
  check(units.length===6&&units.every(u=>u.personnel.current===300&&u.logistics.food===80-turn*2&&u.logistics.ammo===80),'Round '+turn+' preserves personnel and separate food/ammo accounts');
  check(units.every(u=>Math.abs(u.formation.intel_age_min-turn*30)<1e-7),'Round '+turn+' preserves observation minutes');
  check(audit.settlement.resource_teams.every(t=>t.food_spent===t.unit_count*2&&t.ammo_spent===0),'Round '+turn+' report basis records gross food cost and zero ammunition cost');
  check(audit.settlement.goals.filter(g=>!g.condition_sampled).every(g=>g.condition===null),'Round '+turn+' future conditions remain unknown');
  const tasks=await get(base+'/force-organization/tasks'),member=await get(base+'/force-organization/tasks?kind=members&task_id='+tasks.rows[0].id);
  check(member.rows[0].executions===turn,'Round '+turn+' increments the original persistent task exactly once');
  check(turn<12?w.mission.status==='active':w.mission.winner==='red'&&w.campaign_lifecycle.status==='completed','Round '+turn+' has the correct lifecycle boundary');
  samples.push({turn,phase:w.campaign_lifecycle.phase_index+1,report_status:audit.status,issues:audit.issues,
   native_runs:trace.runs.length,food:w.red_units[0].logistics.food,task_executions:member.rows[0].executions,
   preview:audit.preview,engine_meta:d.engine_meta});
  await show();
 }
 await panel.scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/turn-settlement-2026-11-01/http/ui-'+target+'-1440.png'});
 if(target===12){
  check((await panel.getByTestId('lifecycle-current').innerText()).includes('全部阶段已完成'),'UI displays completion of the ten-stage chain');
  check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),'The completed chain cannot silently advance again');
  await page.setViewportSize({width:900,height:1000});await panel.scrollIntoViewIfNeeded();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'The narrow page does not overflow horizontally');
  await page.screenshot({path:'.cache/qa/turn-settlement-2026-11-01/http/ui-final-900.png'});
 }
 const saved=await get(base);await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await show();
 const restored=await get(base);check(JSON.stringify(saved.war_state)===JSON.stringify(restored.war_state)&&JSON.stringify(saved.history)===JSON.stringify(restored.history),'Browser reload preserves world and history without another submission');
 check(errors.length===0,'No browser page errors');
 return {passed:true,start,target,session_id:entry.session_id,checks,samples,api_mocks:false,actual_model:true,actual_afsim:false,
  interpretation_screening_passed:samples.every(s=>s.report_status==='screened'),scope:'Six sourced identities with estimated numerical QA inputs; not a full historical Wanjialing campaign'};
}
