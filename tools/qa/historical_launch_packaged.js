async page=>{
 const API='__API__',OUT='.cache/qa/historical-launch-fix',draft=__GENUINE_DRAFT__,checks=[];
 const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
 await page.unroute(API+'/api/sessions');await page.unroute(API+'/api/scenarios/build');await page.unroute(API+'/api/scenarios/validate');
 // Reuse a genuinely generated/validated staged record already copied to this isolated profile.
 await page.route(API+'/api/scenarios/build',route=>route.fulfill({json:draft}),{times:1});
 await page.evaluate(()=>localStorage.removeItem('gentactix-session'));await page.reload();await page.setViewportSize({width:1440,height:1000});
 assert((await page.title()).includes('3.7.0'),'packaged renderer version 3.7.0');
 assert(await page.evaluate(()=>typeof require==='undefined'&&typeof process==='undefined'),'renderer Node boundary preserved');
 await page.getByLabel('搜索战役').fill('湘西会战');await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-executor').selectOption('narrative');await page.getByTestId('scenario-basis').waitFor();
 const create=page.waitForResponse(r=>r.url()===API+'/api/sessions'&&r.request().method()==='POST');
 await page.getByTestId('launch-start').click();const response=await create;assert(response.ok(),'one primary click prepares draft and creates historical DSH session');
 await page.getByTestId('map-workbench').waitFor({timeout:120000});
 const sid=await page.evaluate(()=>localStorage.getItem('gentactix-session')),path='/api/sessions/'+sid;
 let snap=await(await page.request.get(API+path)).json();
 assert(snap.settings.product_mode==='historical'&&snap.settings.execution_backend==='narrative','workspace retains selected purpose and independent engine');
 assert((await page.getByTestId('execution-kind').textContent()).includes('历史战局推演 · DSH独立推演'),'workspace engine label reflects actual path');
 let view=await(await page.request.get(API+path+'/commands')).json();const first=view.units[0];
 const orders=view.units.map(u=>({unit_id:u.id,action:'hold',duration:'next'}));orders[0]={unit_id:first.id,action:'move',duration:'next',destination:{lat:first.position.lat+.0005,lng:first.position.lng}};
 let r=await page.request.put(API+path+'/commands',{data:{expected_turn:view.turn,revision:view.revision,world_version:view.world_version,director:true,orders}});assert(r.ok(),'human move and opposing hold queue accepted');
 // Refresh the mounted command panel with the saved queue before using the toolbar.
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
 const step=page.waitForResponse(r=>r.url()===API+path+'/next',{timeout:900000});await page.getByRole('button',{name:'推进一轮',exact:true}).click();const sr=await step;snap=await sr.json();assert(sr.ok(),'actual DSH turn commits from packaged UI');
 assert(snap.turn_count===1&&snap.engine_meta.trace_runs>0&&snap.war_state.dsh_execution.effects_source==='dsh_model_estimate'&&!snap.war_state.afsim,'DSH computes turn without false AFSIM receipt');
 const moved=[...snap.war_state.red_units,...snap.war_state.blue_units].find(u=>u.name===first.name);
 assert(Math.abs(moved.lat-orders[0].destination.lat)<.00001&&Math.abs(moved.lng-orders[0].destination.lng)<.00001,'actual DSH candidate honors selected map-coordinate move');
 await page.getByRole('tab',{name:'兵种与保障',exact:true}).click();assert((await page.getByTestId('combined-arms').textContent()).includes('DSH模型估计'),'support panel identifies model-estimated effects');
 await page.screenshot({path:OUT+'/frozen-dsh-historical.png'});
 const exported=await(await page.request.get(API+path+'/export')).json();assert(exported.session.product_mode==='historical'&&exported.session.war_state.dsh_execution,'export retains purpose and DSH effect provenance');
 return {passed:true,checks,session_id:sid,genuine_prior_draft_reused:true,actual_model_turn:true,model_meta:snap.engine_meta};
}
