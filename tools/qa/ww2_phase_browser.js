async page=>{
 const api='http://127.0.0.1:18998',ui='http://127.0.0.1:18981/',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};const id=new URL(location.href).searchParams.get('qa-session');if(id)localStorage.setItem('gentactix-session',id);else localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto(ui+'?qa-source=1');
 await page.getByLabel('搜索战役').fill('万家岭');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');
 await page.getByTestId('generate-historical-scenario').waitFor();
 check(await page.getByLabel('历史起始阶段').inputValue()==='oct7_attack','default selects the supported local phase');
 check((await page.getByTestId('historical-setup').innerText()).includes('默认选择'),'automatic phase choice is disclosed');
 const region=await page.getByTestId('historical-region').innerText();check(region.includes('29.36525')&&region.includes('12 km'),'Moxi reference and finite calculation boundary displayed');
 await page.getByLabel('历史起始阶段').selectOption('campaign_reference');await page.getByTestId('historical-configuration-gap').waitFor();
 check(await page.getByTestId('generate-historical-scenario').count()===0,'explicit unsupported reference phase is respected');
 await page.getByLabel('历史起始阶段').selectOption('oct7_attack');await page.getByTestId('generate-historical-scenario').waitFor();
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' source screen no overflow');
  await page.screenshot({path:'.cache/qa/ww2-phases/source-'+width+'.png'});
 }
 for(const [id,count,label] of [['89333d3012a4',2,'taierzhuang'],['8a7bb5c3f4e1',4,'wanjialing']]){
  const snapshot=await(await page.request.get(api+'/api/sessions/'+id)).json();check(snapshot.turn_count===8,label+' actual API has eight rounds');
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto(ui+'?qa-session='+id);
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   await page.waitForFunction(n=>document.querySelectorAll('.nato-marker').length===n,count);
   check(await page.locator('.nato-marker').count()===count,width+' '+label+' sourced actors rendered');
   await page.locator('#analysis-tab-combined').click();await page.getByTestId('combat-assessment').waitFor();
   const expected=[...snapshot.war_state.red_units,...snapshot.war_state.blue_units];
   check(await page.getByTestId('casualty-breakdown').count()===count,width+' '+label+' classified ledgers rendered');
   for(let i=0;i<expected.length;i++){
    const t=await page.getByTestId('casualty-breakdown').nth(i).innerText(),p=expected[i].personnel;
    check(t.includes('阵亡估计 '+p.killed)&&t.includes('负伤估计 '+p.wounded),width+' '+label+' '+expected[i].name+' exact classified losses');
   }
   const assessment=await page.getByTestId('combat-assessment').innerText();
   check(assessment.includes('本轮历时 30 分钟（1800秒）')&&assessment.includes('标定待完成'),width+' '+label+' single-turn duration and calibration limits visible');
   const history=page.getByTestId('combat-reference');await history.locator('summary').click();
   const reference=await history.innerText();check(reference.includes('中方所报歼敌')&&!reference.includes('阵亡：10000'),width+' '+label+' reported enemy losses are not converted into deaths');
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' '+label+' no overflow');
   await page.getByTestId('combined-unit').first().scrollIntoViewIfNeeded();
   await page.screenshot({path:'.cache/qa/ww2-phases/'+label+'-'+width+'.png'});
  }
 }
 check(!errors.length,'no browser exceptions');return {passed:true,checks,route_mocks:false};
}
