async page=>{
 const api='http://127.0.0.1:18992',ui='http://127.0.0.1:18993/',checks=[],errors=[];
 const sessions=await(await page.request.get(api+'/api/sessions')).json();
 const sid=sessions.sessions[0].session_id;
 const initial=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 if(!initial.sustainment)throw Error('Real snapshot budget required');
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid)},{api,sid});
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label)};
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui);
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  await page.locator('#analysis-tab-combined').click();
  const panel=page.getByTestId('sustainment-budget');await panel.waitFor();
  check((await panel.innerText()).includes('剩余 '+initial.sustainment.remaining_turns+' 轮'),`${width}: actual remaining rounds`);
  for(const team of ['red','blue']){
   const row=page.getByTestId('sustainment-'+team),data=initial.sustainment.teams[team];
   const shortage=data.optimistic_food_shortfall.toLocaleString('zh-CN',{maximumFractionDigits:2});
   if(data.optimistic_food_shortfall>0)check((await row.innerText()).includes('仍缺 '+shortage),`${width}: ${team} actual shortage displayed`);
   if(data.zero_food_count)check((await row.innerText()).includes(data.zero_food_count+' 个实体粮秣已耗尽'),`${width}: ${team} zero-food count`);
  }
  await panel.getByText('估算范围与规则限制',{exact:true}).click();
  check((await panel.innerText()).includes('不能据此推定历史饥饿伤亡'),`${width}: estimates not represented as historical casualties`);
  await panel.scrollIntoViewIfNeeded();
  const box=await panel.boundingBox();check(box&&box.x>=0&&box.x+box.width<=width,`${width}: fits panel`);
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}: no page overflow`);
  await page.screenshot({path:`.cache/qa/sustainment-ui-2026-10-29/runtime-${width}.png`});
 }
 const after=await(await page.request.get(api+'/api/sessions/'+sid)).json();
 check(JSON.stringify(after.war_state)===JSON.stringify(initial.war_state)&&after.turn_count===initial.turn_count,'viewing never advances or modifies authoritative state');
 check(!errors.length,'no component errors');
 return {passed:true,checks,session_id:sid,api_mocks:false,scope:'Isolated copy of real committed T52; no execution or user-save changes'};
}
