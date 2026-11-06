async page=>{
 const checks=[],check=(v,label)=>{if(!v)throw new Error(label);checks.push(label);};
 const field=page.getByTestId('historical-goal-editor');await field.waitFor();
 check(await page.getByLabel('目标方',{exact:true}).inputValue()==='blue','DSH source task creates a blue-owned goal');
 check(await page.getByLabel('目标类型',{exact:true}).inputValue()==='assault','supported local assault rule selected');
 check(await page.getByLabel('目标存续编组').isDisabled(),'unused assault survivor threshold is not editable');
 check((await page.getByTestId('verified-objective').innerText()).includes('有蓝方、无红方'),'verified text describes the actual blue condition');
 const deadline=page.getByLabel('目标截止回合');const original=await deadline.inputValue();
 await deadline.fill('1');check(await page.getByTestId('validate-historical-scenario').isDisabled(),'impossible consecutive condition cannot be submitted');
 check(await page.getByTestId('verified-objective').count()===0,'invalid edit does not retain a verified claim');
 await deadline.fill(original);
 await page.getByLabel('目标方',{exact:true}).focus();await page.keyboard.press('Home');await page.keyboard.press('Tab');
 check(await page.getByLabel('目标方',{exact:true}).inputValue()==='red','goal owner is keyboard editable');
 check(await page.getByLabel('目标类型',{exact:true}).evaluate(e=>e===document.activeElement),'keyboard advances to the next labelled control');
 check(await page.getByTestId('verified-objective').count()===0,'owner edit invalidates its previous native receipt');
 async function validate(){
  const r=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST');
  await page.getByTestId('validate-historical-scenario').click();const answer=await r;
  check(answer.status()===200,'edited configuration really validates through the API');
  const body=await answer.json();page.__objectiveCurrentDraft=body;
  await page.getByTestId('verified-objective').waitFor();return body;
 }
 const red=await validate();check(red.preview_world.mission.definition.objective_team==='red','native edited red definition');
 check((await page.getByTestId('verified-objective').innerText()).includes('有红方、无蓝方'),'revalidated red criteria replace blue text');
 await page.getByLabel('目标方',{exact:true}).selectOption('blue');const blue=await validate();
 check(blue.preview_world.mission.definition.objective_team==='blue','native blue criteria restored by another actual validation');
 check(blue.preview_world.mission.turn===0,'validation does not advance the battle');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await field.scrollIntoViewIfNeeded();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no horizontal document overflow');
  await page.screenshot({path:'.cache/qa/objective-team/editor-'+width+'.png'});
 }
 await page.setViewportSize({width:1440,height:1000});
 const next=page.waitForResponse(r=>/\/api\/sessions$/.test(r.url())&&r.request().method()==='POST');
 await page.getByTestId('launch-start').click();const made=await(await next).json();
 await page.getByTestId('map-workbench').waitFor();
 const snap=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+made.session_id)).json();
 check(snap.war_state.mission.definition.objective_team==='blue','normal frontend launch preserves blue goal ownership');
 check(snap.war_state.afsim.entity_count===2&&snap.turn_count===0,'actual native initialization has both sourced actors');
 page.__objectiveSession=made.session_id;page.__objectiveInitial=snap;
 return {passed:true,checks,session_id:made.session_id,route_mocks:false};
}
