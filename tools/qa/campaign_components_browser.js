async page=>{
 const checks=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label)};
 await page.goto('http://127.0.0.1:18982/?session=1bf8066e8ca8');
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.getByTestId('history-deployment-gap').waitFor();
 check((await page.getByTestId('history-deployment-gap').innerText()).includes('圆圈'),'event-only replay explains that circles are geographic references');
 check(await page.locator('.nato-marker').count()===0,'no fabricated troop positions in source-only replay');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});
  const bounds=await page.getByTestId('history-deployment-gap').boundingBox();
  check(bounds&&bounds.y>150,width+' deployment warning stays clear of top menus');
  await page.screenshot({path:'.cache/qa/cheqiao-complete/replay-gap-'+width+'.png'});
 }
 await page.goto('http://127.0.0.1:18982/?session=713b536dab78');
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.nato-marker').length===4);
 check(await page.getByTestId('history-deployment-gap').count()===0,'positioned operational units have no false deployment gap');
 check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),'existing completed battle remains completed');
 await page.goto('http://127.0.0.1:18983/.qa-campaign.html');
 await page.getByTestId('campaign-editor').waitFor();
 check(await page.locator('[data-campaign-actor]').count()===3,'all configured actors have arrival and fortification editors');
 await page.getByLabel('战役兵力保存比例').fill('0.65');
 check(await page.getByTestId('saved-ratio').innerText()==='0.65','editor changes parent-owned configuration');
 await page.getByRole('button',{name:'增加阻援区域',exact:true}).click();
 check(await page.locator('[data-campaign-region]').count()===2,'blocking regions can be added');
 await page.getByLabel('阻援区域2纬度').fill('34.55');
 await page.getByRole('button',{name:'地图设置阻援区域 2',exact:true}).click();
 check(await page.getByTestId('selected-region').innerText()==='1','map selection emits the correct blocking region index');
 await page.getByRole('button',{name:'移除区域 2',exact:true}).click();
 check(await page.getByRole('button',{name:'移除区域 1',exact:true}).isDisabled(),'last required blocking region cannot be removed');
 const actor=page.locator('[data-campaign-actor]').first();await actor.locator('summary').click();
 const arrival=actor.locator('input[type=datetime-local]');await arrival.fill('1938-03-31T00:30');
 check(await arrival.inputValue()==='1938-03-31T00:30','local arrival time remains editable');
 await page.getByLabel('模拟忙碌').check();
 check(await arrival.isDisabled()&&await page.getByLabel('战役兵力保存比例').isDisabled(),'busy state disables parameter changes');
 await page.getByLabel('模拟忙碌').uncheck();
 check((await page.getByTestId('campaign-goals').innerText()).includes('尚未运行'),'initial goal flags are not presented as achieved results');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),width+' no horizontal overflow');
  await page.screenshot({path:'.cache/qa/cheqiao-complete/campaign-editor-'+width+'.png'});
 }
 check(!errors.length,'no browser script errors');
 return{passed:true,checks,route_mocks:false,scope:'two actual saved sessions plus isolated UI component inputs; not new campaign end-to-end acceptance'};
}
