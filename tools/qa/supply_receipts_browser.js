async page=>{
 const sid='f15bb81a2d85',api='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
 const handler=e=>errors.push(e.message);page.on('pageerror',handler);
 const snap=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 await page.evaluate(id=>localStorage.setItem('gentactix-session',id),sid);
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=receipts-'+Date.now());
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.locator('#analysis-tab-combined').click();await page.getByTestId('classified-receipt').first().waitFor();
  check(await page.getByTestId('classified-receipt').count()===3,width+' all three native classified receipt rows');
  const units=[...snap.war_state.red_units,...snap.war_state.blue_units];
  for(let i=0;i<units.length;i++){
   const text=await page.getByTestId('classified-receipt').nth(i).innerText();
   check(text.includes('炮弹 '+units[i].formation.last_execution.received_shells+' 发')&&text.includes('轮末入账'),width+' '+units[i].name+' exact native delivery');
  }
  check((await page.getByTestId('combined-unit').first().innerText()).includes('本轮炮弹发射 120 发'),width+' shots remain separate from 24 delivered shells');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no document overflow');
  await page.getByTestId('classified-receipt').first().scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/weapon-ranges/receipts-'+width+'.png'});
 }
 check(!errors.length,'no page exceptions');page.removeListener('pageerror',handler);
 return {passed:true,checks,session_id:sid,route_mocks:false};
}
