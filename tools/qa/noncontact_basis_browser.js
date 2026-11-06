async page=>{
 const checks=[],errors=[],builds=[],check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session')});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/historical-scenarios/build'))builds.push(r.url())});
 for(const name of ['中央红军巧渡金沙江','红二六军团抢渡金沙江'])for(const width of [1440,900]){
  const label=name+'/'+width;await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=noncontact-basis');
  await page.getByLabel('搜索战役').fill(name);await page.locator('.battle-option').first().click();
  await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');
  await page.getByTestId('execution-backend').selectOption('afsim');await page.locator('#draft-step').selectOption('15分钟');
  const scope=page.getByTestId('historical-noncontact-scope');await scope.waitFor();
  check((await scope.innerText()).includes('不是整个战役不存在敌军'),label+' noncontact scope visible');
  check(await page.getByTestId('historical-exclusions').count()===1,label+' remote formations retained as references');
  check(await page.getByTestId('generate-historical-scenario').isEnabled(),label+' sourced local phase can generate');
  check(await page.locator('.nato-marker').count()===0,label+' no invented units before generation');
  await page.locator('#draft-step').selectOption('1天');await page.getByTestId('historical-step-gap').waitFor();
  check(await page.getByTestId('generate-historical-scenario').isDisabled(),label+' overlong step rejected before model');
  await page.locator('#draft-step').selectOption('15分钟');
  check(await page.getByTestId('generate-historical-scenario').isEnabled(),label+' feasible step restores generation');
  await scope.scrollIntoViewIfNeeded();check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),label+' no horizontal overflow');
  await page.screenshot({path:'.cache/qa/noncontact/basis-'+(name.startsWith('中央')?'1935':'1936')+'-'+width+'.png'});
 }
 check(!builds.length,'basis/window checks do not launch generation');check(!errors.length,'no application page exceptions');
 return{passed:true,checks,route_mocks:false};
}
