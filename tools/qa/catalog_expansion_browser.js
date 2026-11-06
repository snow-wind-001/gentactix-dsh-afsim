async page => {
 const base='http://127.0.0.1:18998',ui='http://127.0.0.1:18981/?qa=catalog-expansion-v3',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label)};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session')});
 await page.setViewportSize({width:1440,height:1000});await page.goto(ui);
 const examples=[['淞沪会战','city_aug13'],['太原会战','xinkou_oct13'],['第一次长沙','xinqiang_sep18'],
 ['第二次长沙','dayun_sep7'],['第三次长沙','city_jan1'],['桂南会战','kunlun_dec18'],
 ['豫湘桂战役','hengyang_june28'],['衡阳保卫战','zhangjiashan_june28'],['百团大战','shinaoshan_aug21'],
 ['敌后局部反攻','gaogou_apr19'],['车桥战役','cheqiao_mar5'],['缅北滇西','songshan_june4'],['全面反攻与受降','zhangjiakou_aug20']];
 for(const [keyword,phase] of examples){
  await page.getByLabel('搜索战役').fill(keyword);await page.locator('.battle-option').first().click();
  await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');
  await page.getByTestId('historical-basis').waitFor();const menu=page.getByLabel('历史起始阶段');
  await page.locator('#draft-step').selectOption('15分钟');
  await page.waitForFunction(id=>document.querySelector('[aria-label="历史起始阶段"]')?.value===id,phase);
  check(await menu.inputValue()===phase,keyword+' exposes sourced local phase');
  check(await page.getByTestId('historical-goal-guidance').isVisible(),keyword+' shows sourced task and limits');
  check(await page.getByTestId('generate-historical-scenario').isEnabled(),keyword+' can request normal DSH skill');
  check(await page.locator('.nato-marker').count()===0,keyword+' does not draw invented units before configuration');
  if(phase==='xinqiang_sep18'){
   await page.getByTestId('historical-exclusions').locator('summary').click();
   check((await page.getByTestId('historical-exclusions').innerText()).includes('第13师团'),'first Changsha retains unbound division reference');
  }
  await menu.selectOption('reference');await page.getByTestId('historical-configuration-gap').waitFor();
  check(await page.getByTestId('generate-historical-scenario').count()===0,keyword+' cumulative reference cannot act as an opening deployment');
  await page.getByRole('button',{name:'返回选择',exact:true}).click();
 }
 await page.getByLabel('搜索战役').fill('第二次长沙');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.getByTestId('historical-goal-guidance').waitFor();
 check((await page.getByTestId('historical-goal-guidance').innerText()).includes('第4军'),'revised Dayun source uses Fourth Army');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' configuration fits');
  await page.screenshot({path:'.cache/qa/catalog-expansion/catalog-'+width+'.png'});
 }
 check(!errors.length,'no application page exceptions');return {passed:true,checks,route_mocks:false,scope:'actual catalog and phase UI, not complete historical combat'};
}
