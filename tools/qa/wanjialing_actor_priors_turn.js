async page => {
 const sid=await page.evaluate(()=>localStorage.getItem('gentactix-session'));
 const base='http://127.0.0.1:19129/api/sessions/'+sid;
 const initial=await(await page.request.get(base)).json();
 if(initial.turn_count!==0)throw Error('This probe only advances a fresh retained campaign');
 const view=await(await page.request.get(base+'/commands')).json();
 const range=initial.war_state.mission.definition.combined_rules.artillery_range_m/1000;
 const distance=(a,b)=>111.32*Math.hypot(a.position.lat-b.position.lat,(a.position.lng-b.position.lng)*Math.cos(a.position.lat*Math.PI/180));
 const actions=new Map();
 for(const team of ['red','blue']){
  const pairs=view.units.filter(u=>u.team===team&&u.available&&u.capabilities.actions.includes('bombard'))
   .flatMap(u=>view.units.filter(v=>v.team!==team&&v.available).map(v=>({u,v,d:distance(u,v)})))
   .filter(p=>p.d<range*.9).sort((a,b)=>a.d-b.d);
  if(!pairs.length)throw Error('No legal bilateral artillery pair');
  actions.set(pairs[0].u.id,pairs[0].v.id);
 }
 const orders=view.units.map(u=>({unit_id:u.id,action:actions.has(u.id)?'bombard':'hold',duration:'next',...(actions.has(u.id)?{target_id:actions.get(u.id)}:{})}));
 const saved=await page.request.put(base+'/commands',{data:{expected_turn:view.turn,revision:view.revision,world_version:view.world_version,
  orders,control_team:'red',director:true,no_fire:false,intent:'双边人工炮击数值验证，其余明确待命；不是历史伤亡标定'}});
 if(!saved.ok())throw Error((await saved.text()).slice(0,500));
 const before=await(await page.request.get(base)).json();
 if(JSON.stringify(before.war_state)!==JSON.stringify(initial.war_state))throw Error('Queuing mutated authoritative state');
 const advanced=page.waitForResponse(r=>r.url()===base+'/next'&&r.request().method()==='POST',{timeout:180000});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();
 const response=await advanced,snap=await response.json();
 if(!response.ok())throw Error(JSON.stringify(snap).slice(0,1000));
 page.__campaignTurn=snap;
 const units=[...snap.war_state.red_units,...snap.war_state.blue_units];
 if(snap.turn_count!==1||units.length!==22)throw Error('Turn or roster changed unexpectedly');
 for(const u of units){const p=u.personnel;if(p.committed!==p.current+p.casualties+p.noncombat_losses)throw Error('Personnel account broken');
  for(const e of u.equipment)if(e.committed!==e.operational+e.damaged+e.destroyed)throw Error('Equipment account broken');}
 const losses=Object.fromEntries(['red','blue'].map(t=>[t,snap.war_state[t+'_units'].reduce((sum,u)=>sum+u.personnel.casualties,0)]));
 if(!losses.red||!losses.blue)throw Error('Bilateral fire produced no bilateral effects');
 if(await page.locator('.nato-marker').count()!==22)throw Error('Markers lost after settlement');
 await page.screenshot({path:'.cache/qa/wanjialing-estimates-2026-11-01/browser-rc5/turn1-130.png'});
 return {passed:true,session_id:sid,actors:22,manual_orders:22,bilateral_fire_orders:2,losses,time:snap.war_state.current_time,afsim:snap.afsim?.source,
  scope:'Actual API command queue and frontend advance on generated1.3 priors; not historical calibration'};
}
