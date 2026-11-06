async page => {
 const base='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(v,label)=>{if(!v)throw new Error(label);checks.push(label)};
 page.on('pageerror',e=>errors.push(e.message));
 const sessions=await(await page.request.get(base+'/api/sessions')).json();
 const row=sessions.sessions.find(s=>s.scenario==='乌江渡运指挥生命周期QA-afsim');
 check(!!row,'isolated native control world exists');const sid=row.session_id,path=base+'/api/sessions/'+sid;
 const get=async suffix=>(await(await page.request.get(path+suffix)).json());
 const before=await get(''),view=await get('/commands'),order=view.orders.find(o=>o.action==='move');
 check(before.turn_count===2&&!!order,'native world paused at partial crossing T2');
 await page.context().addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',id);},sid);
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=crossing-control');
 await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
 const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();
 await page.getByTestId('map-workbench').waitFor();await page.getByTestId('command-toggle').click();
 let item=page.locator('[data-command-id="'+order.id+'"]');await item.getByRole('button',{name:'编辑',exact:true}).click();
 check(await page.getByTestId('unit-action').inputValue()==='move','edit restores movement action');
 check(await page.getByLabel('持续方式').inputValue()==='until_arrived','edit restores continuous duration');
 await page.getByTestId('enqueue-order').click();
 await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
 const again=await get('/commands');check(again.orders.find(o=>o.unit_id===order.unit_id)?.id===order.id,'saving unchanged destination retains host command identity');
 check(JSON.stringify((await get('')).war_state)===JSON.stringify(before.war_state),'editing queue does not rewrite world');
 item=page.locator('[data-command-id="'+order.id+'"]');await item.getByRole('button',{name:'撤销',exact:true}).click();
 await item.waitFor({state:'detached'});check(!(await get('/commands')).orders.some(o=>o.unit_id===order.unit_id),'UI cancellation removes confirmed queue item');
 check(JSON.stringify((await get('')).war_state)===JSON.stringify(before.war_state),'UI cancellation waits for engine receipt before physical change');
 await page.getByRole('button',{name:'收起指挥面板',exact:true}).click();await page.getByTestId('analysis-tab-combined').click();
 const panel=page.getByTestId('combined-arms');await panel.waitFor();
 check((await panel.getByTestId('crossing-task').innerText()).includes('当前任务已服务'),'current-task work label is accurate');
 check((await panel.getByTestId('crossing-capacity').innerText()).includes('AFSIM执行回执'),'native provenance remains visible');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no overflow '+width);
  await page.screenshot({path:'.cache/qa/crossing-control/queued-cancel-'+width+'.png'});
 }
 check(!errors.length,'no browser exceptions');return {passed:true,checks,session_id:sid,route_mocks:false};
}
