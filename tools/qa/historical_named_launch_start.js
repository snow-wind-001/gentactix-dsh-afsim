async page=>{
 const api='http://127.0.0.1:18993',ui='http://127.0.0.1:18981/',checks=[];
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18993'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto(ui);
 function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
 await page.getByLabel('搜索战役').fill('武汉会战');await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByTestId('historical-configuration-gap').waitFor();
 check(await page.getByTestId('launch-start').isDisabled(),'Missing opposing battle formations cannot silently launch CA proxies');
 check(await page.getByTestId('synthetic-setup').count()===0,'Historical entry no longer mounts teaching composer');
 await page.getByRole('button',{name:'返回选择',exact:true}).click();await page.getByLabel('搜索战役').fill('徐州会战');await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByTestId('historical-configuration-gap').waitFor();
 check(await page.getByTestId('launch-start').isDisabled(),'January phase does not falsely deploy March participants');
 await page.getByLabel('历史起始阶段').selectOption('taierzhuang');await page.getByTestId('historical-basis').waitFor();
 check(await page.getByTestId('launch-start').isEnabled(),'Sourced March phase can generate historical configuration');
 check(await page.locator('#draft-mission').count()===0,'No teaching mission selector in historical entry');
 check(await page.locator('.nato-marker').count()===0,'No invented units before configuration');
 await page.locator('#draft-executor').selectOption('afsim');
 await page.getByLabel('计算参数与推演目标需求').fill('所选台儿庄阶段，30分钟回合，3月23日起算，缺载钟点按假设说明。8回合局部迟滞，保留全部三个真实ID。缺载人数、装备、部署和物资分别明确估计，不宣称完整会战。各部队合理展开并可机动接敌，不能重叠在同一点。');
 await page.getByTestId('generate-historical-scenario').click();
 return {started:true,checks,scope:'Actual browser starts actual DSH/native build; no routes mocked'};
}
