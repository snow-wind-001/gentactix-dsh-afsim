async page=>{
 const api='http://127.0.0.1:18997',sid='86feac781374',checks=[],errors=[];
 const handler=e=>errors.push(e.message);page.on('pageerror',handler);
 const check=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
 if(await page.getByTestId('map-workbench').count()){
  await page.getByRole('button',{name:'推演操作',exact:true}).click();
  await page.getByRole('button',{name:'想定管理',exact:true}).click();
 }
 const back=page.getByRole('button',{name:'返回选择',exact:true});if(await back.count())await back.click();
 await page.getByRole('tab',{name:/^已保存战局/}).click();
 await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
 await page.getByTestId('map-workbench').waitFor();
 const snap=await(await page.request.get(`${api}/api/sessions/${sid}`)).json();
 check(snap.turn_count===12,'actual six-hour committed session restored in frontend');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});
  check(await page.locator('.nato-marker').count()===6,width+' all six real actor markers remain');
  if(!(await page.getByTestId('combined-arms').isVisible()))await page.locator('#analysis-tab-combined').click();
  await page.getByTestId('combat-assessment').waitFor();
  check(await page.getByTestId('combined-unit').count()===6,width+' all native ledgers available');
  const units=[...snap.war_state.red_units,...snap.war_state.blue_units];
  for(let i=0;i<units.length;i++){
   const text=await page.getByTestId('combined-unit').nth(i).innerText();
   check(text.includes(units[i].name)&&text.includes('战斗减员 '+units[i].personnel.casualties),width+' '+units[i].name+' actual cumulative count');
  }
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no page overflow');
  await page.getByTestId('combined-unit').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:'.cache/qa/scenario-staging/final-'+width+'.png'});
 }
 check(errors.length===0,'no page errors in final review');page.removeListener('pageerror',handler);
 return {passed:true,checks,session_id:sid,route_mocks:false};
}
