async page => {
 const snap=page.__scheduleSnap;if(!snap?.session_id)throw Error('Need initialized actual QA world');
 const url='http://127.0.0.1:19130/api/sessions/'+snap.session_id;
 const previous=await (await page.request.get(url)).json();
 if(previous.turn_count!==0)throw Error('This script requires the original unadvanced QA world');
 const command=await (await page.request.get(url+'/commands')).json();
 const orders=command.units.filter(u=>u.available).map(u=>({unit_id:u.id,action:'hold',duration:'next'}));
 const queue=await page.request.put(url+'/commands',{data:{expected_turn:command.turn,revision:command.revision,
  world_version:command.world_version,control_team:'red',director:true,no_fire:true,unit_agents:[],orders}});
 if(!queue.ok())throw Error('Bilateral holds rejected');
 const queued=await (await page.request.get(url)).json();
 if(JSON.stringify(queued.war_state)!==JSON.stringify(previous.war_state))throw Error('Queue altered world before execution');
 page.__scheduleNext={status:'pending',started:Date.now()};
 page.on('response',async r=>{if(r.url()===url+'/next'&&r.request().method()==='POST'){
  page.__scheduleNext={status:'finished',http:r.status(),body:await r.json()};
 }});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();
 return {started:true,orders:orders.length,scope:'API queued bilateral hold; actual frontend advance with1800s delivery period and6h step'};
}
