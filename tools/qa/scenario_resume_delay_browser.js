async page => {
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19132'});
 page.removeAllListeners('request');page.removeAllListeners('response');
 page.__delayRequests=[];page.__delayValidation={status:'pending'};
 page.on('request',r=>{if(r.method()==='POST')page.__delayRequests.push(new URL(r.url()).pathname);});
 page.on('response',async r=>{if(r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST')page.__delayValidation={status:'finished',http:r.status(),body:await r.json()};});
 await page.reload();await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('冀中');
 await page.locator('.battle-option').filter({hasText:'冀中五一反扫荡'}).click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('[data-admission-choice="1.0.0:campaign"]').click();await page.locator('#draft-step').selectOption('6小时');
 const saved=page.getByTestId('completed-historical-configurations');await saved.locator('summary').click();
 await page.locator('[data-open-configuration="948f80815ba841dc9f523a0592d4bbb1"]').click();
 await page.getByTestId('legacy-campaign-delay').waitFor();
 if(page.__delayRequests.some(p=>p.endsWith('/build')||p.endsWith('/resume')))throw Error('Cold open must not regenerate');
 if(!(await page.getByTestId('historical-validation').innerText()).includes('重新验证'))throw Error('Legacy must not claim new delay policy valid');
 await page.getByRole('button',{name:'启用防御迟滞规则',exact:true}).click();
 if(await page.getByTestId('legacy-campaign-delay').count())throw Error('Explicit policy edit missing');
 await page.getByRole('button',{name:'重新装载验证历史配置',exact:true}).click();
 await page.getByTestId('historical-build-progress').waitFor();
 return {started:true,cold_open_without_model:true,explicit_delay_upgrade:true,source_draft:'948f80815ba841dc9f523a0592d4bbb1',
  scope:'Real saved draft GET and explicit manual goal-policy edit; real Native revalidation, not another model generation'};
}
