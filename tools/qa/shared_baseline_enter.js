async page=>{
 const checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};page.on('pageerror',e=>errors.push(e.message));
 await page.waitForFunction(()=>document.querySelectorAll('[data-testid=synthetic-red] details.formation').length===2&&document.querySelector('[data-testid=scenario-validation]')?.textContent?.includes('AFSIM已装载'),{},{timeout:360000});
 const red=page.getByTestId('synthetic-red');await red.getByRole('button',{name:'添加编组',exact:true}).click();
 if(await page.getByRole('button',{name:'返回配置',exact:true}).isVisible())await page.getByRole('button',{name:'返回配置',exact:true}).click();
 const added=red.locator('details.formation').nth(2);await added.locator('summary').click();
 check(await red.locator('details.formation').count()===3,'user can add a derived formation');
 await page.getByRole('button',{name:'删除red编组3',exact:true}).click();check(await red.locator('details.formation').count()===2,'user can remove a derived formation');
 for(const side of ['red','blue']){
  const detail=page.getByTestId('synthetic-'+side).locator('details.formation').nth(1);
  if(!await detail.evaluate(e=>e.open))await detail.locator('summary').click();
 }
 await page.getByLabel('red-1-人员',{exact:true}).fill('1250');await page.getByLabel('blue-1-装甲车辆',{exact:true}).fill('6');
 check(!(await page.getByTestId('scenario-validation').innerText()).includes('已装载核验'),'personnel or equipment edits invalidate validation');
 await page.getByRole('button',{name:'部署red编组2',exact:true}).click();
 const box=await page.locator('.leaflet-container').boundingBox();if(!box)throw new Error('No map');
 await page.locator('.leaflet-container').click({position:{x:box.width*.68,y:box.height*.52}});
 await page.getByTestId('synthetic-setup').waitFor();
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.getByTestId('synthetic-setup').scrollIntoViewIfNeeded();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' derived editor no overflow');
  await page.screenshot({path:'.cache/qa/shared-baseline/editor-'+width+'.png'});
 }
 const validating=page.waitForResponse(r=>r.url().endsWith('/api/scenarios/validate')&&r.request().method()==='POST');
 await page.getByTestId('validate-scenario').click();const response=await validating,draft=await response.json();
 check(response.status()===200&&draft.afsim.entity_count===4,'edited four-unit configuration actually loads into AFSIM');
 const config=draft.configuration;
 check(config.teams.red[1].personnel===1250&&config.teams.blue[1].equipment.armor===6,'edited values preserved in actual load');
 check(config.teams.red[1].position.lng!==117.75008,'map click updates selected formation deployment');
 check(draft.preview_world.blue_units[1].formation.motorized===true,'new armored formation binds motorized execution');
 check(!draft.preview_world.red_units[1].historical_unit_id&&!draft.preview_world.blue_units[1].historical_unit_id,'added units have exercise identity rather than invented historical identity');
 await page.waitForFunction(()=>document.querySelector('[data-testid=scenario-validation]')?.textContent?.includes('AFSIM已装载'));
 const creating=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST');
 await page.getByTestId('launch-start').click();const created=await creating,result=await created.json();check(created.status()===200,'normal synthetic launch accepts self-contained derived draft');
 await page.getByTestId('map-workbench').waitFor();await page.waitForFunction(()=>document.querySelectorAll('.nato-marker').length===4);
 const snap=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+result.session_id)).json();
 check(snap.settings.product_mode==='synthetic'&&snap.time_step==='15分钟'&&snap.war_state.afsim.entity_count===4,'purpose, selected time and native actors preserved');
 check(snap.war_state.historical_initial.phase_id==='urban_opening'&&snap.war_state.mission.id.startsWith('HS-'),'source phase frozen beneath the synthetic exercise');
 check(!errors.length,'no page exceptions');await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'.cache/qa/shared-baseline/initial.png'});
 return {passed:true,checks,session_id:result.session_id,draft_id:draft.id,route_mocks:false};
}
