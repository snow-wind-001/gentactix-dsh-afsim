async page=>{
 const API='http://127.0.0.1:19118',checks=[],samples=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19118'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 const entries=(await get('/sessions')).sessions,definitionHashes=[];
 for(const [engine,fire] of [['narrative',false],['narrative',true],['afsim',true]]){
  const tag=engine+' '+(fire?'fire':'hold');
  const entry=entries.find(s=>s.scenario.startsWith('原生过程预览终验 '+tag+'；'));if(!entry)throw Error('Missing case '+tag);
  const base='/sessions/'+entry.session_id,initial=await get(base);
  check(initial.turn_count<=2,tag+' retains its existing checkpoint without reset');definitionHashes.push(initial.war_state.mission.definition_hash);
  await page.evaluate(id=>localStorage.setItem('gentactix-session',id),entry.session_id);await page.reload();
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  for(let turn=initial.turn_count+1;turn<=2;turn++){
   if(turn===2&&fire){
    const view=await get(base+'/commands'),orders=[];
    const red=view.units.find(u=>u.name==='第159师'),blue=view.units.find(u=>u.team==='blue');
    for(const u of view.units){
     if(!u.available)continue;
     const opponent=u.id===red.id?blue:u.id===blue.id?red:null;
     orders.push(opponent?.available?{unit_id:u.id,action:'fire',target_id:opponent.id,duration:'next'}:{unit_id:u.id,action:'hold',duration:'next'});
    }
    const response=await page.request.put(API+'/api'+base+'/commands',{data:{expected_turn:view.turn,revision:view.revision,world_version:view.world_version,
     orders,control_team:'red',director:true,no_fire:false,unit_agents:[],intent:'第二轮继续执行双方有效直接射击命令，失能单位不重新下令；其余明确待命，不预设损失。'}});
    if(!response.ok())throw Error(await response.text());
   }
   const response=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000});
   await page.getByRole('button',{name:'推进一轮',exact:true}).click();const r=await response,d=await r.json();if(!r.ok())throw Error(JSON.stringify(d));
   const w=d.war_state,trace=(await get(base+'/traces/'+turn)).record,audit=trace.guards.report;
   check(d.turn_count===turn,tag+' round '+turn+' commits once through the UI');
   check(audit.settlement.version==='turn-settlement-2',tag+' round '+turn+' uses the final settlement contract');
   if(engine==='narrative')check(audit.preview?.evidence==='dsh_public_tool_trajectory'&&!w.afsim,tag+' round '+turn+' has actual Native preview proof without AFSIM effects');
   else check(w.afsim.model_skipped&&!audit.preview,tag+' round '+turn+' preserves the AFSIM execution path');
   check(audit.status==='screened',tag+' round '+turn+' has no known report conflicts');
   check(audit.settlement.goals.filter(g=>!g.condition_sampled).every(g=>g.condition===null),tag+' round '+turn+' never turns unsampled conditions into false');
   const units=[...w.red_units,...w.blue_units];
   check(units.every(u=>u.personnel.current+u.personnel.casualties+u.personnel.noncombat_losses===u.personnel.committed),tag+' round '+turn+' conserves the personnel account');
   if(fire)check(w.engagements.length>=2,tag+' round '+turn+' records actual reciprocal fire');
   else check(!w.engagements.length&&units.every(u=>u.logistics.food===80-2*turn&&u.logistics.ammo===80),tag+' round '+turn+' distinguishes food spending from ammunition');
   check(audit.settlement.units.every(u=>u.supply_index_after===Math.min(u.food_after,u.ammo_after)),tag+' round '+turn+' derives displayed supply from actual classified stocks');
   samples.push({engine,fire,turn,session_id:entry.session_id,engagements:w.engagements.length,report_status:audit.status,preview:audit.preview,
    casualties:Object.fromEntries(['red','blue'].map(team=>[team,w[team+'_units'].reduce((n,u)=>n+u.personnel.casualties,0)])),engine_meta:d.engine_meta});
  }
  const snapshot=await get(base);await page.getByRole('tab',{name:'态势与战损',exact:true}).click();
  const losses=page.getByTestId('battlefield-panel');await losses.waitFor({state:'visible'});
  check((await losses.innerText()).includes('第159师')&&(await losses.innerText()).includes('日军第106师团'),tag+' loss panel retains both controlled identities');
  await page.screenshot({path:'.cache/qa/turn-settlement-2026-11-01/http/final-'+engine+'-'+(fire?'fire':'hold')+'-1440.png'});
  await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  const restored=await get(base);check(JSON.stringify(snapshot.war_state)===JSON.stringify(restored.war_state)&&JSON.stringify(snapshot.history)===JSON.stringify(restored.history),tag+' reload does not rerun effects');
 }
 check(definitionHashes.every(h=>h===definitionHashes[0]),'Hold and reciprocal fire use the same frozen input definition across both engines');
 check(errors.length===0,'No browser page errors');
 return {passed:true,checks,samples,api_mocks:false,actual_model:true,actual_afsim:true,scope:'Final-source software QA with sourced identities and estimated parameters; no historical efficacy claim'};
}
