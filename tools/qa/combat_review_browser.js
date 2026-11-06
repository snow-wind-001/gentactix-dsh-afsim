async page=>{
 const api='http://127.0.0.1:18996',ui='http://127.0.0.1:18981/',checks=[],errors=[];
 const list=(await(await page.request.get(api+'/api/sessions')).json()).sessions;
 const session=list.find(s=>s.turn_count===6&&s.scenario.startsWith('bilateral'));
 if(!session)throw new Error('Run combat_review_live first');
 const selected=await(await page.request.get(api+'/api/sessions/'+session.session_id)).json();
 const error=e=>errors.push(e.message);page.on('pageerror',error);
 function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
 await page.context().addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:18996'};localStorage.setItem('gentactix-session',id);},session.session_id);
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui);
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.locator('#analysis-tab-combined').click();await page.getByTestId('combat-assessment').waitFor();
  check((await page.getByTestId('combat-assessment').innerText()).includes('历史同窗口标定待完成'),width+' no false historical fit claim');
  check(await page.getByTestId('unit-combat-review').count()===3,width+' three actual review rows');
  const expected=[...selected.war_state.red_units,...selected.war_state.blue_units];
  for(let i=0;i<expected.length;i++){
   const review=selected.war_state.combat_assessment.units.find(r=>r.name===expected[i].name);
   const text=await page.getByTestId('unit-combat-review').nth(i).innerText();
   check(text.includes('本轮减员 '+review.turn_casualties+' 人')&&text.includes((review.tracked_incoming_max_fire_s/60).toFixed(1)+' 分钟'),width+' '+expected[i].name+' real turn losses and cumulative incoming time');
  }
  const history=page.getByTestId('unit-history-reference');
  check((await history.innerText()).includes('3000')&&await history.locator('a[href^="https://cpc.people.com.cn/"]').count()===1,width+' same-unit source and scope');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no horizontal document overflow');
  await page.getByTestId('unit-combat-review').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:'.cache/qa/combat-review/review-'+width+'.png'});
 }
 check(errors.length===0,'no browser page errors');page.removeListener('pageerror',error);
 return {passed:true,checks,session_id:session.session_id,route_mocks:false};
}
