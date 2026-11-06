async page=>{
 const api='http://127.0.0.1:18998',ui='http://127.0.0.1:18981/',sid='5dd98af5da13',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',id);},sid);
 const snapshot=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 check(snapshot.turn_count===8,'actual API has eight committed rounds');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui+'?qa=zhiluo-results-'+Date.now());
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  check(await page.locator('.nato-marker').count()===3,width+' three sourced-name QA actors on map');
  await page.locator('#analysis-tab-combined').click();await page.getByTestId('combined-arms').waitFor();
  check(await page.getByTestId('combined-unit').count()===3,width+' three formation ledgers');
  const expected=[...snapshot.war_state.red_units,...snapshot.war_state.blue_units];
  for(let i=0;i<expected.length;i++){
   const t=await page.getByTestId('casualty-breakdown').nth(i).innerText(),p=expected[i].personnel;
   check(t.includes('阵亡估计 '+p.killed)&&t.includes('负伤估计 '+p.wounded),width+' '+expected[i].name+' exact classified losses');
  }
  const refs=page.getByTestId('combat-reference');await refs.locator('summary').click();
  const text=await refs.innerText();
  check(text.includes('被俘：5300')&&text.includes('阵亡：未核'),width+' historical prisoners remain separate from unknown deaths');
  check((await page.getByTestId('combat-assessment').innerText()).includes('历史同窗口标定待完成'),width+' calibration remains explicitly pending');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no overflow');
  await refs.scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/change-paging/zhiluo-results-'+width+'.png'});
 }
 check(!errors.length,'no browser exceptions');
 return {passed:true,checks,route_mocks:false,session_id:sid};
}
