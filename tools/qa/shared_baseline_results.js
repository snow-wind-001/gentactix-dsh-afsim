async page=>{
 const api='http://127.0.0.1:18998',checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 const error=e=>errors.push(e.message);page.on('pageerror',error);
 for(const [sid,prefix] of [['ab9e42f20993','combat'],['ba36ec26585a','arrival']]){
  const snap=await(await page.request.get(api+'/api/sessions/'+sid)).json(),units=[...snap.war_state.red_units,...snap.war_state.blue_units];
  await page.context().addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',id);},sid);
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa='+prefix);
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   check(await page.locator('.nato-marker').count()===units.length,width+' '+prefix+' all four actors remain on the map');
   await page.locator('#analysis-tab-combined').click();await page.getByTestId('combined-arms').waitFor();
   check(await page.getByTestId('combined-unit').count()===4,width+' '+prefix+' all four actual ledgers rendered');
   for(let i=0;i<units.length;i++){
    const text=await page.getByTestId('combined-unit').nth(i).innerText(),p=units[i].personnel;
    check(text.includes('战斗减员 '+p.casualties)&&text.includes('阵亡估计 '+p.killed)&&text.includes('负伤估计 '+p.wounded),width+' '+units[i].name+' classified loss ledger matches native state');
   }
   if(prefix==='combat'){
    check((await page.getByTestId('combat-assessment').innerText()).includes('15 分钟')&&(await page.getByTestId('combat-assessment').innerText()).includes('历史同窗口标定待完成'),width+' actual round duration and uncalibrated status displayed');
    const source=page.getByTestId('unit-history-reference');check((await source.innerText()).includes('死伤约 3000')&&await source.locator('a[href^="https://cpc.people.com.cn/"]').count()===1,width+' same historical unit source stays separate from simulated losses');
   }else{
    const armor=page.getByTestId('combined-unit').filter({hasText:'蓝方演习装甲队'});
    check((await armor.innerText()).includes('燃油限制机动')&&(await armor.innerText()).includes('80.4 米'),width+' partial motion has honest fuel limitation and actual distance');
   }
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' '+prefix+' no document overflow');
   await page.getByTestId('combined-unit').first().scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/shared-baseline/'+prefix+'-'+width+'.png'});
   if(prefix==='arrival'){await page.getByTestId('combined-unit').last().scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/shared-baseline/armor-'+width+'.png'});}
  }
 }
 check(errors.length===0,'no browser page exceptions');page.removeListener('pageerror',error);return {passed:true,checks,route_mocks:false};
}
