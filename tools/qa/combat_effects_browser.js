async page=>{
 const api='http://127.0.0.1:18994',ui='http://127.0.0.1:18981/',checks=[],errors=[];
 const error=e=>errors.push(e.message);page.on('pageerror',error);
 function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
 const sessions=(await(await page.request.get(api+'/api/sessions')).json()).sessions;
 let selected;
 for(const s of sessions){
  if(s.turn_count!==6||!s.scenario.startsWith('sustained'))continue;
  const world=await(await page.request.get(api+'/api/sessions/'+s.session_id)).json();
  if(world.war_state.combat_reference?.version==='aggregate-fire-cycles-2.2'){selected=world;break;}
 }
 if(!selected)throw new Error('Run current actual native fire acceptance first');
 await page.context().addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:18994'};localStorage.setItem('gentactix-session',id);},selected.session_id);
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui);
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.locator('#analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
  check(await page.getByTestId('combined-unit').count()===3,width+' three actual actors and ledgers');
  const expected=[...selected.war_state.red_units,...selected.war_state.blue_units];
  for(let i=0;i<expected.length;i++){
   const row=page.getByTestId('combined-unit').nth(i),p=expected[i].personnel;
   const text=await row.getByTestId('casualty-breakdown').innerText();
   check(text.includes('阵亡估计 '+p.killed)&&text.includes('负伤估计 '+p.wounded)&&text.includes('既有待分类 '+p.unclassified_casualties),width+' '+expected[i].name+' classified counts from native state');
   check((await row.getByTestId('fire-cycles').innerText()).includes('周期 '+expected[i].formation.last_execution.fire_cycles+' 次'),width+' '+expected[i].name+' actual repeated cycles');
  }
  const reference=page.getByTestId('combat-reference');await reference.locator('summary').click();
  const text=await reference.innerText();
  check(text.includes('0.25')&&text.includes('不是台儿庄已知分项')&&text.includes('第31师'),width+' historical reference and unmeasured assumptions visible');
  check(await reference.locator('a[href^="http"]').count()>0,width+' sources accessible as links');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no document overflow');
  await page.screenshot({path:'.cache/qa/combat-effects/workbench-'+width+'.png'});
  await reference.locator('summary').click();await page.getByTestId('casualty-breakdown').first().scrollIntoViewIfNeeded();
  check(await page.getByTestId('casualty-breakdown').first().isVisible(),width+' first loss ledger visible after closing references');
  await page.screenshot({path:'.cache/qa/combat-effects/loss-ledger-'+width+'.png'});
 }
 check(errors.length===0,'No browser page errors');page.removeListener('pageerror',error);
 return {passed:true,session_id:selected.session_id,checks,route_mocks:false,scope:'Actual native 3-hour QA, no historical deployment or efficacy calibration claim'};
}
