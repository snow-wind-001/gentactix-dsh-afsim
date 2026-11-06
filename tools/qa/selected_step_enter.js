async page=>{
 const checks=[],check=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.waitForFunction(()=>document.querySelector('[data-testid=historical-validation]')?.textContent?.includes('AFSIM实际装载'),{},{timeout:360000});
 check(await page.locator('#draft-step').inputValue()==='15分钟','top-level selection remains 15 minutes after native build');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.getByTestId('historical-selected-step').scrollIntoViewIfNeeded();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no horizontal overflow');
  await page.screenshot({path:'.cache/qa/selected-step/selected-'+width+'.png'});
 }
 await page.locator('#draft-step').selectOption('30分钟');
 check(!(await page.getByTestId('historical-validation').innerText()).includes('已通过'),'editing selection invalidates native-load receipt');
 check(await page.getByTestId('validate-historical-scenario').isEnabled(),'changed clock exposes revalidation');
 await page.screenshot({path:'.cache/qa/selected-step/invalidated.png'});
 await page.locator('#draft-step').selectOption('15分钟');
 check(!(await page.getByTestId('historical-validation').innerText()).includes('已通过'),'restoring selection does not resurrect stale receipt');
 const validated=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST');
 await page.getByTestId('validate-historical-scenario').click();
 const response=await validated,draft=await response.json();check(response.status()===200,'edited clock revalidates in native AFSIM');
 check(draft.parameters.clock.time_step==='15分钟','revalidated parameters use the selected label');
 await page.waitForFunction(()=>document.querySelector('[data-testid=historical-validation]')?.textContent?.includes('AFSIM实际装载'));
 const creating=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST');
 await page.getByTestId('launch-start').click();const created=await creating,payload=created.request().postDataJSON(),body=await created.json();
 check(created.status()===200&&payload.time_step==='15分钟','normal launch sends authoritative selection');
 await page.getByTestId('map-workbench').waitFor();
 const snapshot=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+body.session_id)).json();
 check(snapshot.time_step==='15分钟'&&snapshot.war_state.mission.definition.time_step==='15分钟','created session and frozen definition retain selected step');
 check(snapshot.turn_count===0&&snapshot.war_state.afsim.entity_count===2,'native init does not advance the clock');
 await page.waitForFunction(()=>document.querySelectorAll('.nato-marker').length===2);
 check(await page.locator('.nato-marker').count()===2,'both sourced historical actors shown');
 check(!errors.length,'no page exceptions during revalidation and launch');
 await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'.cache/qa/selected-step/initial.png'});
 return {passed:true,checks,session_id:body.session_id,draft_id:draft.id,time_step:snapshot.time_step,route_mocks:false};
}
