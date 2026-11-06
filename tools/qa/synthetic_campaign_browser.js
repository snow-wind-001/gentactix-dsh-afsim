async page=>{
 const API='http://127.0.0.1:19103',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 page.on('pageerror',e=>errors.push(e.message));
 await page.getByTestId('synthetic-red').waitFor({timeout:900000});
 const red=page.getByTestId('synthetic-red');
 const count=await red.locator('details.formation').count();
 check(count===5||count===6,'Actual DSH source generation reaches normal synthetic editor');
 const oldName=await red.getByLabel('red-0-名称',{exact:true}).inputValue();
 if(count===5){
  await red.getByRole('button',{name:'添加编组',exact:true}).click();
  await page.locator('.draft-map-prompt').waitFor();
  const map=page.getByRole('region',{name:'想定部署地图',exact:true}),box=await map.boundingBox();
  await map.click({position:{x:box.width*.45,y:box.height*.48}});
  await page.locator('.scenario-window').waitFor({state:'visible'});
 }
 for(const index of [5,1])if(!await red.getByLabel(`red-${index}-名称`,{exact:true}).isVisible())
  await red.locator('details.formation').nth(index).locator('summary').click();
 await red.getByLabel('red-5-名称',{exact:true}).fill('前端新增演习部队');
 await red.getByLabel('red-1-名称',{exact:true}).fill('前端更名演习单位');
 await red.getByRole('button',{name:'删除red编组1',exact:true}).click();
 check((await red.innerText()).includes('5 个编组'),'Add, remove and rename through actual editor controls');
 const pending=page.waitForResponse(r=>r.url()===API+'/api/scenarios/validate'&&r.request().method()==='POST',{timeout:120000});
 await page.getByTestId('validate-scenario').click();const response=await pending,draft=await response.json();
 if(!response.ok())throw Error(JSON.stringify(draft));
 check(draft.afsim.entity_count===6,'AFSIM actually loads all edited campaign actors');
 const world=draft.preview_world,names=world.red_units.concat(world.blue_units).map(u=>u.name);
 check(!names.includes(oldName)&&names.includes('前端新增演习部队')&&names.includes('前端更名演习单位'),'Authoritative roster matches editor changes');
 check(Object.keys(world.campaign.actors).sort().join()===names.sort().join(),'Process rows match all and only current roster');
 check(world.red_units.filter(u=>u.exercise_unit_id).length===2,'Added and renamed units have independent exercise process identities');
 check(world.mission.definition.historical_synthetic.campaign_revision==='synthetic-campaign-1','Explicit process revision is frozen');
 const initialized=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
 await page.getByRole('button',{name:'创建并进入推演',exact:true}).click();const init=await initialized,snap=await init.json();
 if(!init.ok())throw Error(JSON.stringify(snap));await page.getByTestId('map-workbench').waitFor();
 const sid=snap.session_id;
 const get=async path=>{const r=await page.request.get(API+path);if(!r.ok())throw Error(await r.text());return r.json();};
 const cs=await get('/api/sessions/'+sid+'/commands');const unit=snap.war_state.red_units.find(u=>u.name==='前端新增演习部队');
 const put=await page.request.put(API+'/api/sessions/'+sid+'/commands',{data:{expected_turn:cs.turn,revision:cs.revision,world_version:cs.world_version,
  control_team:'red',director:true,no_fire:false,unit_agents:[],orders:cs.units.map(u=>({unit_id:u.id,duration:'next',
   ...(u.name===unit.name?{action:'move',destination:{lat:unit.lat+.0005,lng:unit.lng}}:{action:'hold'})}))}});
 if(!put.ok())throw Error(await put.text());
 const finished=page.waitForResponse(r=>r.url().endsWith('/next')&&r.request().method()==='POST',{timeout:120000});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();const next=await finished,after=await next.json();
 if(!next.ok())throw Error(JSON.stringify(after));
 const moved=after.war_state.red_units.find(u=>u.name===unit.name);
 check(moved.lat!==unit.lat||moved.lng!==unit.lng,'New exercise actor actually moves after UI advance');
 check(after.turn_count===1&&after.war_state.afsim.orders.length===6,'All six confirmed orders execute once');
 await page.screenshot({path:'.cache/qa/synthetic-campaign-2026-10-31/browser/edited-native-1440.png'});
 check(errors.length===0,'No browser page errors');
 return {passed:true,checks,session_id:sid,draft_id:draft.id,actual_dsh_generation:true,actual_afsim:true,
  api_mocks:false,queue_input:'API confirmed batch, UI advance',scope:'Explicit estimated local initial state, not full historical campaign'};
}
