async page=>{
 const base='http://127.0.0.1:18998',sid='c422a7d70429',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};page.on('pageerror',e=>errors.push(e.message));
 const state=await(await page.request.get(base+'/api/sessions/'+sid)).json(),boat=state.war_state.combined_arms.bridge.ferry_state.boats[0];
 check(state.turn_count===3,'actual standalone DSH T3 committed');
 check(boat.phase==='returning'&&boat.from_bank==='a'&&boat.bank==='b'&&boat.trips===1,'actual landing retains original return bank');
 check(!state.war_state.afsim,'standalone result does not fabricate AFSIM execution');
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session','c422a7d70429')});
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=ferry-landed-'+width);
  await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
  const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();await page.getByTestId('map-workbench').waitFor();
  await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
  check(await page.locator('.nato-marker').count()===6,width+' standalone ground leaves conserved');
  await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms'),receipt=panel.getByTestId('ferry-state');
  const text=await receipt.innerText();check(text.includes('DSH估计')&&text.includes('空艇返航')&&text.includes('完成登岸 1 航次'),width+' actual estimated landing and provenance visible');
  check((await panel.getByTestId('formation-group-row').innerText()).includes('1600 / 投入 1600'),width+' parent count conserved after landing');
  const marker=page.locator('.ferry-boat-marker');await marker.hover();check((await page.locator('.leaflet-tooltip').last().innerText()).includes('乘载0/5人'),width+' empty return marker uses actual manifest');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no page overflow');
  await page.screenshot({path:'.cache/qa/ferry-model/narrative-landed-'+width+'.png'});
 }
 check(!errors.length,'no application page exceptions');return{passed:true,checks,route_mocks:false};
}
