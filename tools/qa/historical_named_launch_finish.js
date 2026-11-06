async page=>{
 const api='http://127.0.0.1:18993',checks=[];function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
 await page.getByTestId('historical-validation').waitFor({timeout:300000});
 check((await page.getByTestId('historical-validation').innerText()).includes('实际装载'),'Actual DSH generation and native load complete');
 check(await page.locator('[data-historical-actor]').count()===3,'All three historical actor IDs editable without representative formations');
 const count=page.getByLabel('第31师人员');const original=Number(await count.inputValue());await count.fill(String(original-100));
 check((await page.getByTestId('historical-validation').innerText()).includes('改变'),'Editing numerical estimates invalidates load receipt');
 await page.getByRole('button',{name:'地图部署第31师',exact:true}).click();
 const map=page.locator('.leaflet-container');const box=await map.boundingBox();await map.click({position:{x:box.width*.45,y:box.height*.53}});
 await page.getByTestId('validate-historical-scenario').waitFor();
 check(await page.getByTestId('validate-historical-scenario').isEnabled(),'Map placement leaves an actionable revalidation');
 for(const engine of ['narrative','afsim']){
  await page.locator('#draft-executor').selectOption(engine);
  const response=page.waitForResponse(r=>r.url()===api+'/api/historical-scenarios/validate'&&r.request().method()==='POST');
  await page.getByTestId('validate-historical-scenario').click();const result=await(await response).json();
  if(result.detail)throw new Error(result.detail);
  check(result.execution_backend===engine,engine+' validation stays with selected engine');
  check(engine==='afsim'?result.afsim?.entity_count===3:result.afsim===null,engine+' receipt matches actual execution scope');
 }
 const create=page.waitForResponse(r=>r.url()===api+'/api/sessions'&&r.request().method()==='POST');
 await page.getByTestId('launch-start').click();const response=await create;const payload=response.request().postDataJSON();const result=await response.json();
 if(!result.session_id)throw new Error(JSON.stringify(result));
 check(!payload.mission_id&&!payload.synthetic_configuration&&!!payload.historical_parameters&&!!payload.scenario_draft_id,'Normal frontend submits sourced historical parameters, never CA configuration');
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 const snapshot=await(await page.request.get(api+'/api/sessions/'+result.session_id)).json();const world=snapshot.war_state;
 check(world.mission.id.startsWith('HO-')&&world.afsim.entity_count===3,'Normal launch creates three actual native actors');
 check(world.red_units[0].personnel.current===original-100,'Edited historical estimate survives native initialization');
 check(world.mission.definition.goal.includes('600米'),'Goal display uses actual program condition');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});
  check(await page.locator('.nato-marker').count()===3,width+' renders all historical actors');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' has no document overflow');
  await page.screenshot({path:`.cache/qa/historical-launch-native/workspace-${width}.png`});
 }
 await page.getByRole('button',{name:'红方 第31师',exact:true}).click();await page.getByTestId('command-panel').waitFor();
 check(await page.getByTestId('unit-action').isEnabled(),'Historical unit enters normal command system');
 return {passed:true,session_id:result.session_id,checks,route_mocks:false,scope:'Actual normal UI, native DSH skill, map edit, engine validation and native initialization; partial Xuzhou dataset'};
}
