async page=>{
 const checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 page.on('pageerror',e=>errors.push(e.message));
 for(const [sid,engine] of [['1451c64ff5cc','afsim'],['a1823edb93b4','narrative']]){
  await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid);},sid);
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=objective-team-results');
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   check((await page.getByTestId('execution-kind').innerText()).includes('蓝方胜'),engine+'/'+width+' displays blue victory');
   check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),engine+'/'+width+' terminal goal disables advance');
   await page.getByTestId('top-status').click();const panel=page.getByTestId('mission-panel');
   check((await panel.getByTestId('mission-objective-owner').innerText()).includes('蓝方'),engine+'/'+width+' owner retained after reload');
   check((await panel.innerText()).includes('有蓝方、无红方'),engine+'/'+width+' canonical condition retains the correct side');
   const scope=panel.locator('details').filter({has:page.getByText('资料范围与建模假设',{exact:true})});
   check(await scope.count()===1&&await scope.getAttribute('open')===null,engine+'/'+width+' long assumptions are collapsed initially');
   await panel.getByText('目标进度、补给账与重放凭据',{exact:true}).click();
   check(await panel.getByRole('button',{name:'对照上一轮：蓝方全部原地待命',exact:true}).isVisible(),engine+'/'+width+' progress and comparison remain accessible');
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no horizontal document overflow');
   await page.screenshot({path:'.cache/qa/objective-team/result-'+engine+'-'+width+'.png'});
  }
 }
 check(errors.length===0,'no page exceptions in both actual engine results');
 return {passed:true,checks,route_mocks:false};
}
