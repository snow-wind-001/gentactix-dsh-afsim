async page=>{
 const api='http://127.0.0.1:18992',ui='http://127.0.0.1:18993/',checks=[],errors=[];
 const sessions=await(await page.request.get(api+'/api/sessions')).json();const sid=sessions.sessions[0].session_id;
 const initial=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 const check=(v,label)=>{if(!v)throw Error(label);checks.push(label)};
 check(initial.sustainment?.dynamics?.version==='time-sustainment-1','real native checkpoint has time model');
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid)},{api,sid});
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui);
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.locator('#analysis-tab-combined').click();
  const panel=page.getByTestId('sustainment-budget');await panel.waitFor();
  check((await panel.innerText()).includes('时间模型'),'time-based rule visible '+width);
  check((await panel.innerText()).includes('48 小时'),'configured threshold visible '+width);
  for(const team of ['red','blue']){
   const row=page.getByTestId('sustainment-'+team),value=initial.sustainment.teams[team];
   check((await row.innerText()).includes('最大累计缺粮 '+value.max_shortage_hours.toLocaleString('zh-CN',{maximumFractionDigits:2})),'actual native shortage displayed '+team+' '+width);
   check((await row.innerText()).includes('不是阵亡'),'noncombat distinction '+team+' '+width);
  }
  await panel.scrollIntoViewIfNeeded();const box=await panel.boundingBox();
  check(box&&box.x>=0&&box.x+box.width<=width,'panel fits '+width);
  await page.screenshot({path:`.cache/qa/support-dynamics-ui/runtime-${width}.png`});
 }
 const after=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 check(JSON.stringify(after.war_state)===JSON.stringify(initial.war_state),'viewing leaves authoritative world unchanged');
 check(!errors.length,'no page exceptions');return{passed:true,checks,api_mocks:false,scope:'isolated real native checkpoint; no map-tile availability claim'};
}
