async page=>{
 const API='http://127.0.0.1:18988',UI='http://127.0.0.1:18981/',out='.cache/qa/historical-initial-audit',results=[];
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18988'};});
 await page.goto(UI);await page.setViewportSize({width:1440,height:1000});
 const snapshots=[];
 for(const id of ['25b9dd98f20d','363ca17808ab','ab37bbbcf93c','d5504aa32755','da22573149ba','f9011ef0540e']){
  const response=await page.request.get(API+'/api/sessions/'+id);if(!response.ok())throw new Error(await response.text());const snap=await response.json();snapshots.push(snap);
  if(!snap.war_state){results.push({id,initialized:false,units:0,markers:0});continue;}
  await page.evaluate(id=>localStorage.setItem('gentactix-session',id),id);await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  const units=[...snap.war_state.red_units,...snap.war_state.blue_units].length,markers=await page.locator('.nato-marker').count();
  results.push({id,initialized:true,units,markers,replay:!!snap.war_state.history_replay});await page.screenshot({path:out+'/saved-'+id+'.png'});
 }
 const original=snapshots.find(v=>v.session_id==='ab37bbbcf93c'),probe=JSON.parse(JSON.stringify(original));
 probe.war_state.red_units=[{name:'QA坐标探针（非历史部署）',type:'步兵',lat:34.20442,lng:117.28386,hp:100}];
 await page.route(API+'/api/sessions/'+original.session_id,route=>route.fulfill({json:probe}));
 await page.evaluate(id=>localStorage.setItem('gentactix-session',id),original.session_id);await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
 const probeMarkers=await page.locator('.nato-marker').count();
 await page.unroute(API+'/api/sessions/'+original.session_id);
 return {audit_completed:true,original_game_files_modified:false,results,
  replay_renderer_probe:{fixture_only:true,input_units:1,drawn_unit_markers:probeMarkers,shows_renderer_early_return:probeMarkers===0}};
}
