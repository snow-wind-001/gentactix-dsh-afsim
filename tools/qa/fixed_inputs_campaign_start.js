async page => {
 page.__campaignFixed={status:'idle'};
 page.on('response',async r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST')
  page.__campaignFixed={status:'finished',http:r.status(),body:await r.json(),request:r.request().postDataJSON()};});
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19131'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089/');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');await page.locator('#draft-step').selectOption('1小时');
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 const picker=page.getByLabel('会战窗口',{exact:true});await picker.locator('option[value="WJL-oct6-10@1.3.0"]').waitFor({state:'attached'});
 const read=page.waitForResponse(r=>r.url().includes('/api/historical-scenarios/basis?')&&r.url().includes('campaign_window_version=1.3.0'));
 await picker.selectOption('WJL-oct6-10@1.3.0');const response=await read;const basis=await response.json();
 if(!response.ok()||basis.actors.length!==22)throw Error('Need22exclusive campaign actors and1.3priors');
 const editor=page.getByTestId('fixed-parameter-inputs');await editor.locator('summary').click();
 const fields=basis.fixed_parameter_fields.filter(f=>f.path[0]==='actors'&&f.path.at(-1)==='personnel');
 if(fields.length!==22||fields.some(f=>!Number.isInteger(f.value)||f.value<=0))throw Error('Missing numerical model priors');
 for(const field of fields){
  await page.getByLabel('固定参数配置对象',{exact:true}).selectOption(field.group);
  await page.getByLabel('固定参数数值项目',{exact:true}).selectOption(JSON.stringify(field.path));
  await page.getByLabel('固定参数指定数值',{exact:true}).fill(String(field.value));await page.getByTestId('add-fixed-parameter').click();
 }
 if(await editor.locator('li').count()!==22)throw Error('Not all campaign numerical inputs selected');
 const instruction='使用窗口1.3.0明确标为模型估计的完整公共及22单位基线，验证跨分片固定输入，不是历史兵额、实测部署或全役验收。先读skill及basis；公共条件与单位均已有数值。保留fixed_parameters及全部其他数值，公共片只patch assumptions、每单位片只patch本片全部actor ID的assumption，说明复核了来源、窗口和范围且未标定。必须真实update并取得revision。不要重写相同数值，不删除双边6目标、单位或余部，不改变1小时和目标完成制。人数0误差只针对固定计算先验，不宣称历史准确；保留后勤、地形、航空、C2、粒度等尚未完整标定的限制。最终真实validate，返回版本/哈希/简短说明。';
 await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(instruction);
 page.__campaignFixed={status:'pending',started:Date.now()};await page.getByTestId('generate-historical-scenario').click();
 return {started:true,actual_frontend:true,actors:22,fixed_personnel_inputs:22,scope:'Wanjialing optional1.3 numerical priors, cross-Native-shard retention and actual AFSIM initial load; not historic strengths or full5day process'};
}
