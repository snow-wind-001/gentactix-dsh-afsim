async page=>{
 const base='http://127.0.0.1:18998',sid='d8e13b4024ba',checks=[];
 const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 const before=await(await page.request.get(base+'/api/sessions/'+sid)).json();
 const parts=before.war_state.red_units.filter(u=>u.formation_part);
 await page.setViewportSize({width:1440,height:1000});
 const panel=page.getByTestId('command-panel');if(!await panel.isVisible())await page.getByTestId('command-toggle').click();
 const menu=panel.getByLabel('单位名单（含无坐标单位）');
 for(const part of parts){
  const option=menu.locator('option').filter({hasText:part.name});await menu.selectOption(await option.getAttribute('value'));
  await panel.getByTestId('unit-action').selectOption(part.formation_part.part_id==='main'?'hold':'move');
  if(part.formation_part.part_id!=='main'){
   await panel.getByRole('button',{name:'地图选目的地',exact:true}).click();
   const marker=page.locator('.nato-marker[title='+JSON.stringify('红方 '+part.name)+']');const b=await marker.boundingBox(),map=page.locator('.map-fill'),m=await map.boundingBox();
   if(!b||!m)throw Error('part marker or map missing');
   await map.click({position:{x:b.x-m.x+b.width/2+15,y:b.y-m.y+b.height/2-15}});
   await panel.waitFor({state:'visible'});check((await panel.getByTestId('map-destination').innerText()).includes('目的地 '),'selected leaf accepts real map pointer destination');
  }
  const response=page.waitForResponse(r=>r.url().includes('/commands')&&r.request().method()==='PUT');
  await panel.getByTestId('enqueue-order').click();check((await response).ok(),'UI confirms order for '+part.formation_part.part_id);
 }
 const commands=await(await page.request.get(base+'/api/sessions/'+sid+'/commands')).json();
 check(commands.orders.length===2&&new Set(commands.orders.map(o=>o.unit_id)).size===2,'two independent commands are persisted under distinct IDs');
 check(commands.orders.some(o=>o.action==='hold')&&commands.orders.some(o=>o.action==='move'),'main hold and detachment move coexist');
 const after=await(await page.request.get(base+'/api/sessions/'+sid)).json();
 check(JSON.stringify(after.war_state)===JSON.stringify(before.war_state),'enqueue does not teleport or execute either part');
 while(await panel.locator('.queued').count()){
  const count=await panel.locator('.queued').count();
  const response=page.waitForResponse(r=>r.url().includes('/commands')&&r.request().method()==='DELETE');
  await panel.locator('.queued').first().getByRole('button',{name:'撤销',exact:true}).click();check((await response).ok(),'UI cancels one queued part order');
  await page.waitForFunction(n=>document.querySelectorAll('[data-testid=command-panel] .queued').length<n,count);
 }
 const final=await(await page.request.get(base+'/api/sessions/'+sid)).json();
 check(JSON.stringify(final.war_state)===JSON.stringify(before.war_state),'cancel keeps physical world unchanged');
 await panel.getByRole('button',{name:'收起指挥面板'}).click();
 const ledger=page.getByTestId('formation-group-ledger');if(!await ledger.isVisible())await page.getByTestId('analysis-tab-combined').click();
 await ledger.waitFor({state:'visible'});await page.screenshot({path:'.cache/qa/formation-partitions/launched-ledger-1440.png'});
 return{passed:true,checks,route_mocks:false,session_id:sid};
}
