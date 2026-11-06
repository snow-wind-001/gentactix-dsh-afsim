async page=>{
 const checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session','3fbde648595e');});
 const response=await page.request.get('http://127.0.0.1:18998/api/sessions/3fbde648595e'),snapshot=await response.json();
 check(snapshot.turn_count===16&&snapshot.war_state.current_time==='1938-03-24 12:00','actual source session completed 16 selected steps');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa-selected-result='+width);
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.nato-marker').length===2);
  await page.locator('#analysis-tab-combined').click();await page.getByTestId('combat-assessment').waitFor();
  check((await page.getByTestId('combat-assessment').innerText()).includes('本轮历时 15 分钟（900秒）'),width+' display shows one exact 15-minute round');
  const units=[...snapshot.war_state.red_units,...snapshot.war_state.blue_units];
  for(let i=0;i<units.length;i++){
   const text=await page.getByTestId('casualty-breakdown').nth(i).innerText(),p=units[i].personnel;
   check(text.includes('阵亡估计 '+p.killed)&&text.includes('负伤估计 '+p.wounded),width+' '+units[i].name+' classified losses match native ledger');
  }
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' final result no horizontal overflow');
  await page.getByTestId('combined-unit').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:'.cache/qa/selected-step/results-'+width+'.png'});
 }
 check(!errors.length,'no result-screen page exceptions');
 return {passed:true,checks,route_mocks:false};
}
