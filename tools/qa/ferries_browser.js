async page=>{
 const base='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};const sid=new URL(location.href).searchParams.get('qa-session');if(sid)localStorage.setItem('gentactix-session',sid);else localStorage.removeItem('gentactix-session')});
 for(const [engine,sid] of [['afsim','b1bf364d9c67'],['narrative','c422a7d70429']]){
  let state;
  for(let n=0;n<900;n++){
   state=await(await page.request.get(base+'/api/sessions/'+sid)).json();if(state.turn_count>=1)break;
   const p=await(await page.request.get(base+'/api/sessions/'+sid+'/progress')).json();
   if(!p.active&&p.failed_operation)throw Error(engine+' actual operation failed; inspect existing turn rather than retrying');
   await page.waitForTimeout(1000);
  }
  check(state.turn_count===1,engine+' actual T1 committed');
  const boat=state.war_state.combined_arms.bridge.ferry_state.boats[0];
  check(boat.phase==='outbound'&&boat.manifest_personnel===5,engine+' actual boat still underway');
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa-build=ferry-v1&qa-session='+sid);
   await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
   const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();await page.getByTestId('map-workbench').waitFor();
   await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
   check(await page.locator('.nato-marker').count()===6,engine+'/'+width+' six ground leaves and no duplicated parent');
   const marker=page.locator('.ferry-boat-marker');await marker.waitFor();check(await marker.count()===1,engine+'/'+width+' separate boat marker');
   await marker.hover();check((await page.locator('.leaflet-tooltip').last().innerText()).includes('乘载5/5人'),engine+'/'+width+' boat tooltip exposes manifest and capacity');
   await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms'),receipt=panel.getByTestId('ferry-state');await receipt.waitFor();
   const text=await receipt.innerText();check(text.includes(engine==='afsim'?'AFSIM原生':'DSH估计'),engine+'/'+width+' source label matches engine');
   check(text.includes('载客航行')&&text.includes('登船时 5 人')&&text.includes('完成登岸 0 航次'),engine+'/'+width+' boarding not mislabeled landed');
   check((await panel.getByTestId('formation-group-row').innerText()).includes('1600 / 投入 1600'),engine+'/'+width+' parent personnel remains conserved');
   await page.getByTestId('command-toggle').click();const command=page.getByTestId('command-panel'),menu=command.getByLabel('单位名单（含无坐标单位）');
   const option=menu.locator('option').filter({hasText:boat.passenger});await menu.selectOption(await option.getAttribute('value'));
   const actions=await command.getByTestId('unit-action').locator('option').evaluateAll(nodes=>nodes.map(n=>n.value));
   check(actions.length===2&&actions.includes('hold')&&actions.includes('move'),engine+'/'+width+' aboard actions match supported control');
   await command.getByRole('button',{name:'收起指挥面板'}).click();if(!await receipt.isVisible())await page.getByTestId('analysis-tab-combined').click();
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no page overflow');
   await page.screenshot({path:'.cache/qa/ferry-model/'+engine+'-'+width+'.png'});
  }
 }
 check(!errors.length,'no application page exceptions');return{passed:true,checks,route_mocks:false};
}
