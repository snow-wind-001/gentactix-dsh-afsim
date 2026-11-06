async page=>{
 const checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 page.on('pageerror',e=>errors.push(e.message));
 const listing=await (await page.request.get('http://127.0.0.1:18998/api/sessions')).json();
 const row=listing.sessions.find(r=>r.scenario.startsWith('KW06-autumn1951')&&r.turn_count===8);
 check(!!row,'owned completed Maryang QA is available');
 await page.context().addInitScript(sid=>{
  window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid);
 },row.session_id);
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=korean-loss');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.getByTestId('analysis-tab-combined').click();
  const panel=page.getByTestId('combined-arms');await panel.waitFor();
  check(await panel.getByTestId('combined-unit').count()===2,width+' both sourced formations visible');
  const ref=panel.getByTestId('unit-history-reference');
  check(await ref.count()===1,width+' same-ID reference attaches only to 3RAR');
  const text=await ref.innerText();
  check(text.includes('104')&&text.includes('15')&&text.includes('89')&&text.includes('继续执勤'),width+' wounded duty status and alternate report retained');
  check(text.includes('投入人数未核')&&text.includes('局部小时窗口'),width+' unknown historical strength and time limits visible');
  check((await ref.locator('a').getAttribute('href')).includes('anzacportal.dva.gov.au'),width+' source links to the actual DVA article');
  const losses=await panel.getByTestId('casualty-breakdown').allTextContents();
  check(losses[0].includes('阵亡估计 5')&&losses[0].includes('负伤估计 18'),width+' red native classified losses');
  check(losses[1].includes('阵亡估计 42')&&losses[1].includes('负伤估计 127'),width+' blue native classified losses');
  check((await panel.getByTestId('combat-assessment').innerText()).includes('30 分钟'),width+' last turn is 30 minutes rather than cumulative four hours');
  await ref.scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/korean-series/reference-'+width+'.png'});
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no document overflow');
 }
 check(errors.length===0,'no page exceptions after QA initialization');
 return {passed:true,checks,route_mocks:false};
}
