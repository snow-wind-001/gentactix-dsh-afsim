async page => {
 const b=page.__campaignFixed;if(b?.http!==200||Object.keys(b.body.parameters.actors).length!==22)throw Error('Need actual22actor model result');
 const root='.cache/qa/fixed-parameters-2026-11-01/browser';
 const init=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
 await page.getByTestId('launch-start').click();const response=await init;const initial=await response.json();
 if(!response.ok()||initial.turn_count!==0)throw Error('Campaign initialization failed');page.__campaignFixedInitial=initial;
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 if(await page.locator('.nato-marker').count()!==22)throw Error('Missing campaign map units');
 await page.screenshot({path:root+'/campaign-fixed-initial.png'});
 const url='http://127.0.0.1:19131/api/sessions/'+initial.session_id;
 const queue=await (await page.request.get(url+'/commands')).json();
 const orders=queue.units.filter(u=>u.available).map(u=>({unit_id:u.id,action:'hold',duration:'next'}));
 if(orders.length!==22)throw Error('Not all campaign units are controllable');
 const accepted=await page.request.put(url+'/commands',{data:{expected_turn:queue.turn,revision:queue.revision,
  world_version:queue.world_version,control_team:'red',director:true,no_fire:true,unit_agents:[],orders}});
 if(!accepted.ok())throw Error('Campaign holds rejected');
 page.__campaignFixedNext={status:'pending'};
 page.on('response',async r=>{if(r.url()===url+'/next'&&r.request().method()==='POST')page.__campaignFixedNext={status:'finished',http:r.status(),body:await r.json()};});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();
 return {started:true,session_id:initial.session_id,initial_turn:0,map_markers:22,orders:22,scope:'Real frontend enter/advance after22fixed inputs; API queued bilateral holds, not a full historical campaign'};
}
