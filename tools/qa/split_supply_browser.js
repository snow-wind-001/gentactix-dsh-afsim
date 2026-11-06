async page=>{
 const api='http://127.0.0.1:18994',ui='http://127.0.0.1:18995/',checks=[],errors=[];
 const {session_id:sid}=await(await page.request.get(ui+'qa-session.json')).json();
 const initial=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 const check=(v,label)=>{if(!v)throw Error(label);checks.push(label)};
 check(initial.sustainment?.supply_distribution?.version==='split-stocks-1','real native split model');
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid)},{api,sid});
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui);
  const resume=page.getByRole('button',{name:'返回当前战局',exact:true});
  await resume.or(page.locator('#analysis-tab-combined')).first().waitFor();
  if(await resume.isVisible())await resume.click();
  await page.locator('#analysis-tab-combined').click();
  const panel=page.getByTestId('sustainment-budget');await panel.waitFor();
  check(!(await panel.innerText()).includes('无法补粮'),'no obsolete full-ammo warning '+width);
  for(const team of ['red','blue']){
   const row=page.getByTestId('sustainment-'+team),value=initial.sustainment.teams[team];
   for(const [label,key] of [['仓库粮秣','warehouse_food'],['仓库弹药','warehouse_ammo']]){
    const field=row.locator('dl div').filter({has:page.getByText(label,{exact:true})});
    check(await field.locator('dd').innerText()===value[key].toLocaleString('zh-CN',{maximumFractionDigits:2}),'actual '+key+' '+team+' '+width);
   }
  }
  await page.getByRole('button',{name:'目标与运行',exact:true}).click();
  const table=page.getByTestId('mission-resource-table');
  await table.evaluate(el=>{let p=el.parentElement;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement}});
  await table.scrollIntoViewIfNeeded();
  check(await table.getByRole('columnheader',{name:'质量当量',exact:true}).count()===1,'mass label '+width);
  const rows=table.locator('tbody tr');check(await rows.count()===initial.war_state.mission.ledger.length,'all unit receipts '+width);
  for(let i=0;i<await rows.count();i++){
   const cells=await rows.nth(i).locator('td').allTextContents(),r=initial.war_state.mission.ledger[i];
   check(Number(cells[3])===r.delivery&&Number(cells[4])===r.food_received&&Number(cells[5])===r.ammo_received,'separate delivery values '+i+' '+width);
  }
  const box=await table.boundingBox();check(box&&box.x>=0&&box.x+box.width<=width,'table scroll container fits '+width);
  await page.screenshot({path:`.cache/qa/split-supply-ui/runtime-${width}.png`});
 }
 const after=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 check(JSON.stringify(after.war_state)===JSON.stringify(initial.war_state),'viewing leaves world unchanged');
 check(!errors.length,'no page exceptions');return{passed:true,checks,api_mocks:false};
}
