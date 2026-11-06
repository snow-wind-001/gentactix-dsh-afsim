async page=>{
 const checks=[],errors=[],base='http://127.0.0.1:18990';
 const check=(v,s)=>{if(!v)throw new Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));
 const list=await(await page.request.get(base+'/api/sessions')).json();
 const chosen=list.sessions.find(s=>s.scenario==='多渡点原生受控QA（非全战役复原）');
 check(!!chosen,'isolated real API session exists');
 await page.context().addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:18990'};localStorage.setItem('gentactix-session',id)},chosen.session_id);
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18991/');
  await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
  const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();
  await page.getByTestId('map-workbench').waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.crossing-corridor').length===2);
  check(await page.locator('.nato-marker').count()===4,width+' four source-bound actors, no duplication');
  check(await page.locator('.crossing-barrier').count()===1,width+' one shared declared river');
  check(await page.locator('.crossing-corridor').count()===2,width+' two independent passage corridors');
  await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
  check(await panel.getByTestId('combined-bridge').count()===2,width+' both facility states visible');
  const receipts=await panel.getByTestId('crossing-capacity').allTextContents();
  check(receipts.length===2&&receipts.every(s=>s.includes('AFSIM执行回执')),width+' both native receipt sources visible');
  check(receipts[0].includes('500.00')&&receipts[1].includes('300.00'),width+' capacities are not combined');
  check(await panel.getByTestId('crossing-task').count()===2,width+' actual task progress retained');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no page overflow');
  await page.screenshot({path:'.cache/qa/crossing-network-ui-2026-10-29/map-'+width+'.png'});
 }
 check(!errors.length,'no browser exceptions');return{passed:true,checks,route_mocks:false,session_id:chosen.session_id};
}
