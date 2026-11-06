async page => {
 const initial=page.__fixedSnapshot;if(!initial?.session_id)throw Error('Actual initialized fixed-input world required');
 const url='http://127.0.0.1:19131/api/sessions/'+initial.session_id;
 const before=await (await page.request.get(url)).json();if(before.turn_count!==0)throw Error('Expected unadvanced QA world');
 const queue=await (await page.request.get(url+'/commands')).json();
 const orders=queue.units.filter(u=>u.available).map(u=>({unit_id:u.id,action:'hold',duration:'next'}));
 const accepted=await page.request.put(url+'/commands',{data:{expected_turn:queue.turn,revision:queue.revision,
  world_version:queue.world_version,control_team:'red',director:true,no_fire:true,unit_agents:[],orders}});
 if(!accepted.ok())throw Error('Fixed bilateral command queue rejected');
 const queued=await (await page.request.get(url)).json();if(JSON.stringify(before.war_state)!==JSON.stringify(queued.war_state))throw Error('Queue mutated world before execution');
 page.__fixedNext={status:'pending'};
 page.on('response',async r=>{if(r.url()===url+'/next'&&r.request().method()==='POST')page.__fixedNext={status:'finished',http:r.status(),body:await r.json()};});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();
 return {started:true,queued_orders:orders.length,scope:'API bilateral holds/no_fire; real frontend advance, scheduled numerical QA, not full battle'};
}
