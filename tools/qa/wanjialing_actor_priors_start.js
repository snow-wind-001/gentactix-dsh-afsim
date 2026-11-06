async page => {
 page.removeAllListeners('response');
 await page.unroute('**/api/historical-scenarios/build');
 const root='/home/spikebai/gitcode/Gentactix/.cache/qa/wanjialing-estimates-2026-11-01/browser-rc5';
 page.__estimateBuild={status:'not_started'};
 page.on('response',async r=>{
  if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST'){
   const data=await r.json();page.__estimateBuild={status:'finished',http:r.status(),id:data.id??null,body:data};
  }
 });
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19129'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('1小时');
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 const picker=page.getByLabel('会战窗口',{exact:true});
 await picker.locator('option[value="WJL-oct6-10@1.3.0"]').waitFor({state:'attached'});
 await picker.selectOption('WJL-oct6-10@1.3.0');await page.getByTestId('campaign-window-scope').waitFor();
 const evidence=page.getByTestId('campaign-window-evidence');await evidence.locator('summary').click();
 if(await page.locator('[data-estimate-actor]').count()!==22)throw Error('Missing per-unit priors');
 await page.screenshot({path:root+'/priors-1440.png'});await evidence.locator('summary').click();
 const instruction='本次使用窗口1.3.0的可重放计算先验，验证地面22单位会战配置，不称完整史实或已标定。公共条件与单位已有显式数值基线；先读skill、范围、来源和当前分片，再复核。不改变已满足约束的数值，不重写整份JSON；公共片patch仅写assumptions，单位片patch覆盖本片全部actor ID且各自仅写assumption。说明人数、装备、到场、位置、库存为人工选择的模型先验而非史实实有数，未知事实保持未知；必须取得真实update有效回执。遵守启动页1小时、目标完成制，保留双边六目标的身份、依赖与承担者，保留39身份处理及22候选，不作计算分队，不投入未核余部。保留时间保障模型，不把编组工作量说成口粮吨数；单仓、平面路径、缺航空、道路、多仓与按人员标定仍是限制。不把当前可受令等同史实同时到场，不按未来历史命令强制行动。末片全量validate须valid，不用口头通过代替工具。';
 await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(instruction);
 page.__estimateBuild={status:'pending',started:Date.now()};
 await page.getByTestId('generate-historical-scenario').click();
 return {started:true,scope:'Real frontend->Native staged builder->AFSIM load; explicit numerical priors, not full historical acceptance'};
}
