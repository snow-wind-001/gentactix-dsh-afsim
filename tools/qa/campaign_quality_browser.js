async page=>{
 const API='http://127.0.0.1:19110',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19110'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 const sessions=(await get('/sessions')).sessions;
 for(const [engine,turn,index] of [['narrative',3,74],['afsim',1,78],['fresh-first',1,78]]){
  const prefix=engine==='fresh-first'?'首轮目标状态复核；':'补给与讲解真实验收 '+engine+'；';
  const entry=sessions.find(s=>s.scenario.startsWith(prefix));if(!entry)throw Error('Run real quality QA first');
  const before=await get('/sessions/'+entry.session_id),world=JSON.stringify(before.war_state);
  await page.evaluate(id=>localStorage.setItem('gentactix-session',id),entry.session_id);await page.reload();
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  await page.getByTestId('command-toggle').click();const panel=page.getByTestId('command-panel');await panel.waitFor({state:'visible'});
  await panel.getByRole('combobox',{name:'单位名单（含无坐标单位）',exact:true}).selectOption({label:'红 · 第90师'});
  const resources=await panel.getByTestId('selected-unit-resources').innerText();
  check(resources.includes('粮食 '+index)&&resources.includes('弹药 80')&&resources.includes('补给指数 '+index),engine+' unit control shows matching food/ammo/index');
  await page.getByRole('tab',{name:'态势与战损',exact:true}).click();const battlefield=page.getByTestId('battlefield-panel');await battlefield.waitFor({state:'visible'});
  const row=battlefield.getByTestId('operational-units').locator('tbody tr').filter({hasText:'第90师 / 红'});
  check((await row.locator('td').nth(6).innerText())===index.toFixed(1),engine+' actual battlefield row uses the same derived index');
  check((await battlefield.innerText()).includes('粮食与弹药工作量较低值'),engine+' index scope is explained without claiming delivery');
  await page.screenshot({path:'.cache/qa/campaign-quality-2026-10-31/'+engine+'/ui-resources.png'});
  await page.getByRole('tab',{name:'动态战报',exact:true}).click();const report=page.locator('.reports .report').first();await report.waitFor({state:'visible'});
  const prose=await report.innerText();
  check(prose.includes('第161师万家岭投入部')&&!prose.includes('五个步兵师')&&!prose.includes('waiting_dependency'),engine+' published report preserves the partial formation and named goal status');
  check(prose.includes('当前条件成立；前置目标尚未达成'),engine+' report separates predicate truth from dependency progress');
  if(engine==='fresh-first')check(!prose.includes('pending'),'Fresh first-round UI does not publish the input-pending verdict');
  check((await get('/sessions/'+entry.session_id)).turn_count===turn&&JSON.stringify((await get('/sessions/'+entry.session_id)).war_state)===world,engine+' review does not modify physics or repeat a turn');
  if(engine==='narrative'){
   await page.setViewportSize({width:900,height:1000});await page.screenshot({path:'.cache/qa/campaign-quality-2026-10-31/'+engine+'/ui-report-900.png'});
   const box=await page.getByTestId('analysis-panel').boundingBox();check(!!box&&box.x>=0&&box.x+box.width<=900,'Narrow report panel remains inside viewport');
   await page.setViewportSize({width:1440,height:1000});
  }
 }
 check(errors.length===0,'No browser page errors');return {passed:true,checks,actual_api:true,actual_model_input:true,actual_afsim_input:true,api_mocks:false};
}
