async page=>{
 const API='http://127.0.0.1:19116',checks=[],samples=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 page.on('pageerror',e=>errors.push(e.message));
 const entry=(await get('/sessions')).sessions.find(s=>s.scenario.startsWith('单世界十阶段验收 afsim；'));if(!entry)throw Error('Run setup-ui first');
 const base='/sessions/'+entry.session_id,initial=await get(base),start=initial.turn_count,target=start===0?4:12;
 check(start===0||start===4,'Actual checkpoint starts at expected browser segment');
 await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19116'};localStorage.setItem('gentactix-session',id);},entry.session_id);
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const panel=page.getByTestId('campaign-lifecycle'),button=page.getByRole('button',{name:/目标与运行/});
 const show=async()=>{if(!await panel.isVisible())await button.click();await panel.waitFor({state:'visible'});};
 await show();check((await panel.innerText()).includes('不改变参战单位集合'),'Stage scope is visible rather than implying unit refits');
 await panel.getByRole('button',{name:'显示全部 10 个阶段',exact:true}).click();
 check(await panel.locator('[data-phase-id]').count()===10,'All ten stages can be expanded');
 for(let turn=start+1;turn<=target;turn++){
  const response=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:180000});
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();const r=await response,d=await r.json();if(!r.ok())throw Error(JSON.stringify(d));
  check(d.turn_count===turn,'Round '+turn+' committed exactly once');
  const w=d.war_state,l=w.campaign_lifecycle;
  check(w.simulation_clock.elapsed_seconds===turn*1800,'Round '+turn+' physical clock is continuous');
  check(w.red_units.every(u=>u.logistics.food===80-2*turn&&u.personnel.current===300),'Round '+turn+' food and personnel ledgers are continuous');
  check(w.afsim.model_skipped===true,'Round '+turn+' uses actual native execution with confirmed commands');
  check(turn===12?w.mission.winner==='red'&&l.status==='completed':w.mission.status==='active','Round '+turn+' has correct global lifecycle boundary');
  samples.push({turn,phase:l.phase_index+1,food:w.red_units[0].logistics.food,definition_hash:w.mission.definition_hash});
  await show();await page.waitForFunction(label=>document.querySelector('[data-testid=lifecycle-current]')?.textContent?.includes(label),'QA阶段'+(l.phase_index+1));
  if(turn===4||turn===5){
   check((await panel.getByTestId('lifecycle-duration').innerText()).includes(turn===4?'30分钟':'1.0小时'),'Gap duration changes at round '+turn);
   check(w.campaign_plan.nodes.milestone10.status==='waiting_phase','Future milestone remains unscored during the gap');
  }
 }
 await panel.scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/campaign-lifecycle-2026-10-31/afsim/ui-'+target+'-1440.png'});
 if(target===12){
  check((await panel.getByTestId('lifecycle-current').innerText()).includes('全部阶段已完成'),'Final UI shows completion of all stages');
  await page.setViewportSize({width:900,height:1000});const box=await page.getByTestId('mission-panel').boundingBox();
  check(!!box&&box.x>=0&&box.x+box.width<=900,'Stage panel remains within narrow viewport');
  await page.screenshot({path:'.cache/qa/campaign-lifecycle-2026-10-31/afsim/ui-final-900.png'});
 }
 const saved=JSON.stringify((await get(base)).war_state);await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await show();
 check((await get(base)).turn_count===target&&JSON.stringify((await get(base)).war_state)===saved,'Reload preserves world and stage without repeating a round');
 check(errors.length===0,'No browser page errors');
 return {passed:true,start,target,session_id:entry.session_id,checks,samples,actual_afsim:true,model_calls:false,api_mocks:false};
}
