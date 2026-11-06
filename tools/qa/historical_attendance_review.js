async page=>{
 const api='http://127.0.0.1:18995',id='3853b3a26924',checks=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
 const snapshot=await(await page.request.get(api+'/api/sessions/'+id)).json();
 await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18995'};localStorage.setItem('gentactix-session',sid);},id);
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  check(await page.locator('.nato-marker').count()===6,width+' all six actual ground actors remain on map including disabled unit');
  await page.locator('#analysis-tab-combined').click();await page.getByTestId('combined-arms').waitFor();
  check(await page.getByTestId('combined-unit').count()===6,width+' all six personnel/equipment ledgers retained');
  const text=await page.getByTestId('combined-arms').innerText();
  check(text.includes('非摩托化机动')&&text.includes('摩托化机动'),width+' mixed mobility labels visible');
  check(text.includes('小武器射击尝试')&&text.includes('模型估计'),width+' estimated shooting attempts labeled separately from physical inventory');
  const first=page.getByTestId('combined-unit').nth(1);await first.scrollIntoViewIfNeeded();
  const unit=snapshot.war_state.red_units[1];check((await first.innerText()).includes('战斗减员 '+unit.personnel.casualties),width+' rendered casualty total matches native state');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no horizontal overflow');
  await page.screenshot({path:'.cache/qa/historical-attendance/actual-'+width+'.png'});
 }
 check(errors.length===0,'No browser page errors');return {passed:true,checks,session_id:id,route_mocks:false,scope:'Actual source-ID modeled battle, not complete historical reconstruction'};
}
