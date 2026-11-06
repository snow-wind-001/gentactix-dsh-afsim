async page=>{
 const API='http://127.0.0.1:19120',checks=[],samples=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const response=await page.request.get(API+'/api'+path);if(!response.ok())throw Error(await response.text());return response.json();};
 page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19120'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
 const entries=(await get('/sessions')).sessions;
 const entry=entries.find(s=>s.scenario.startsWith('单位参与状态验收 afsim-ui；'));
 if(!entry)throw Error('Missing prepared UI case');
 const base='/sessions/'+entry.session_id,initial=await get(base);
 check(initial.turn_count===0,'Fresh UI case, without replacing another campaign');
 await page.evaluate(id=>localStorage.setItem('gentactix-session',id),entry.session_id);await page.reload();
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 let view=await get(base+'/commands');const unit=view.units.find(u=>u.name==='第159师');
 const panel=page.getByTestId('command-panel');
 await page.getByTestId('command-toggle').click();await panel.getByRole('combobox').first().selectOption(unit.id);
 check((await panel.getByTestId('unit-participation-status').innerText()).includes('在场作战'),'Actual unit participation is visible');
 async function advance(label){
  const wait=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:180000});
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();const response=await wait,snapshot=await response.json();
  if(!response.ok())throw Error(JSON.stringify(snapshot));
  check(snapshot.war_state.afsim.model_skipped,label+' uses confirmed commands without another model call');
  check(snapshot.war_state.afsim.returncode===0,label+' has an actual native engine receipt');
  const current=(await get(base+'/commands')).units.find(u=>u.id===unit.id);
  samples.push({label,turn:snapshot.turn_count,participation:current.capabilities.participation,
    personnel:current.personnel,logistics:current.logistics,position:current.position});
  await panel.getByRole('button',{name:'刷新命令',exact:true}).click();
  await panel.getByTestId('unit-participation-status').filter({hasText:current.capabilities.participation.label}).waitFor();
  return {snapshot,current};
 }
 async function mapMove(kind,anchor,offset){
  await panel.getByTestId('unit-action').selectOption('move');
  await panel.getByTestId('unit-participation').selectOption(kind);
  check((await panel.getByTestId('participation-intent').innerText()).includes('实际回执'),'Intent does not claim completed movement');
  const original=page.locator('.nato-marker[aria-label^="红方 '+anchor+'"]');
  const box=await original.boundingBox();if(!box)throw Error('Missing actual marker '+anchor);
  await panel.getByRole('button',{name:'地图选目的地',exact:true}).click();
  await page.mouse.click(box.x+box.width/2+offset.x,box.y+box.height/2+offset.y);
  await panel.waitFor({state:'visible'});
  check((await panel.getByTestId('map-destination').innerText()).startsWith('目的地 '),'Pointer selects the final destination without typed coordinates');
  const saved=page.waitForResponse(r=>r.url()===API+'/api'+base+'/commands'&&r.request().method()==='PUT');
  await panel.getByTestId('enqueue-order').click();const response=await saved;if(!response.ok())throw Error(await response.text());
  const queued=(await response.json()).orders.find(o=>o.unit_id===unit.id);
  check(queued.participation===kind&&queued.duration==='until_arrived','UI retains explicit participation and continuous movement');
  return queued.destination;
 }
 await mapMove('withdraw','第159师',{x:0,y:-22});
 const rear=await advance('Withdrawal');
 check(rear.current.capabilities.participation.status==='reserve','Arrival enters rear waiting');
 check(rear.current.personnel.current===unit.personnel.current,'Withdrawal does not remove personnel');
 check(rear.current.logistics.food<unit.logistics.food,'Withdrawal charges actual food');
 check(!rear.current.capabilities.actions.includes('fire'),'Rear attack is unavailable');
 check(await page.locator('.nato-marker[data-unit-participation="reserve"]').count()===1,'Rear marker stays visible at its actual position');
 await page.screenshot({path:'.cache/qa/unit-participation-2026-11-01/integration/rear-1440.png'});
 await page.setViewportSize({width:900,height:1000});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Narrow workspace has no document horizontal overflow');
 await page.screenshot({path:'.cache/qa/unit-participation-2026-11-01/integration/rear-900.png'});
 await page.setViewportSize({width:1440,height:1000});
 await panel.getByTestId('unit-action').selectOption('hold');
 const saved=page.waitForResponse(r=>r.url()===API+'/api'+base+'/commands'&&r.request().method()==='PUT');
 await panel.getByTestId('enqueue-order').click();check((await saved).ok(),'Explicit rear waiting can be queued');
 const waited=await advance('Rear waiting');
 check(waited.current.capabilities.participation.status==='reserve','Rear waiting preserves status');
 check(waited.current.logistics.food<rear.current.logistics.food,'Rear waiting continues consumption');
 await mapMove('reenter','第90师',{x:0,y:0});const back=await advance('Reentry');
 check(back.current.capabilities.participation.status==='deployed','Actual reentry completes before control resumes');
 check(back.current.capabilities.participation.entity_id===rear.current.capabilities.participation.entity_id,'The same entity returns');
 check(back.current.personnel.current===unit.personnel.current,'Reentry does not restore or drop personnel');
 const final=JSON.stringify(back.snapshot.war_state);await page.reload();
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const restored=await get(base);check(JSON.stringify(restored.war_state)===final,'Reload keeps the exact committed world');
 check(errors.length===0,'No page JavaScript errors');
 return {passed:true,session_id:entry.session_id,checks,samples,actual_afsim:true,actual_model:false,api_mocks:false,
  scope:'Normal visible unit/map command path; not full historical or off-map acceptance'};
}
