async page=>{
 const base='http://127.0.0.1:18998',sid='b1bf364d9c67',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session','b1bf364d9c67')});
 const state=await(await page.request.get(base+'/api/sessions/'+sid)).json();check(state.turn_count===6,'actual API reached T6');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=ferry-complete-'+width);
  await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
  const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();await page.getByTestId('map-workbench').waitFor();
  await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
  check(await page.locator('.nato-marker').count()===6,width+' ground leaves conserved');
  await page.getByTestId('analysis-tab-combined').click();const receipt=page.getByTestId('ferry-state');
  check((await receipt.innerText()).includes('靠岸待命')&&(await receipt.innerText()).includes('完成登岸 1 航次'),width+' completed voyage and empty return visible');
  const marker=page.locator('.ferry-boat-marker');await marker.hover();
  check((await page.locator('.leaflet-tooltip').last().innerText()).includes('乘载0/5人'),width+' empty boat displayed separately');
  await page.getByTestId('command-toggle').click();const panel=page.getByTestId('command-panel'),menu=panel.getByLabel('单位名单（含无坐标单位）');
  const option=menu.locator('option').filter({hasText:'先遣分队'});await menu.selectOption(await option.getAttribute('value'));
  await panel.getByRole('button',{name:'本单位决策／执行回执',exact:true}).click();const records=panel.getByRole('region',{name:'单位决策记录'});await records.waitFor();
  const hold=records.locator('.receipt').filter({hasText:'T+2'});check((await hold.innerText()).includes('随艇'),width+' actual hold-aboard reason visible');
  check((await records.innerText()).includes('T+3'),width+' actual landing round remains in unit history');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no page overflow');
  await page.screenshot({path:'.cache/qa/ferry-model/continued-'+width+'.png'});
 }
 check(!errors.length,'no application page exceptions');return{passed:true,checks,route_mocks:false};
}
