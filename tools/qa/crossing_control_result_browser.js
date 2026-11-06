async page => {
 const base='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(ok,s)=>{if(!ok)throw new Error(s);checks.push(s)};page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};const sid=new URL(location.href).searchParams.get('qa-session');if(sid)localStorage.setItem('gentactix-session',sid);});
 const list=await(await page.request.get(base+'/api/sessions')).json();
 for(const engine of ['afsim','narrative']){
  const row=list.sessions.find(s=>s.scenario==='乌江渡运指挥生命周期QA-'+engine);check(!!row,engine+' real isolated session exists');
  const state=await(await page.request.get(base+'/api/sessions/'+row.session_id)).json();check(state.turn_count===(engine==='afsim'?4:5),engine+' real lifecycle turns complete');
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa-session='+row.session_id+'&qa-build=crossing-distance-v2');
   await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
   const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();await page.getByTestId('map-workbench').waitFor();
   await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
   check((await panel.getByTestId('crossing-task').innerText()).includes('当前任务已服务'),engine+'/'+width+' task amount uses current-task label');
   check((await panel.getByTestId('crossing-capacity').innerText()).includes(engine==='afsim'?'AFSIM执行回执':'DSH估计回执'),engine+'/'+width+' correct execution provenance');
   await page.getByTestId('command-toggle').click();const command=page.getByTestId('command-panel');await command.waitFor({state:'visible'});
   await command.locator('[data-command-id]').filter({hasText:'军委'}).getByRole('button',{name:'编辑',exact:true}).click();
   check((await command.getByTestId('movement-distance').innerText()).includes('距离不代表本轮可到达'),engine+'/'+width+' distance does not promise arrival while crossing is queued');
   await command.getByRole('button',{name:'本单位决策／执行回执',exact:true}).click();const records=page.getByRole('region',{name:'单位决策记录'});await records.waitFor();
   check((await records.innerText()).includes('已撤销')&&(await records.innerText()).includes('此前已耗容量不退回'),engine+'/'+width+' cancellation receipt and debit remain in history');
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no page overflow');
   await records.locator('.receipt').filter({hasText:'已撤销'}).scrollIntoViewIfNeeded();
   await page.screenshot({path:'.cache/qa/crossing-control/'+engine+'-final-'+width+'.png'});
  }
 }
 check(!errors.length,'no browser exceptions');return{passed:true,checks,route_mocks:false};
}
