async page => {
 page.removeAllListeners('response');page.__scheduleBuild={status:'not_started'};
 page.on('response',async r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST'){
  const body=await r.json();page.__scheduleBuild={status:'finished',http:r.status(),id:body.id??null,body};
 }});
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19130'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('徐州');
 await page.locator('.battle-option').filter({hasText:'徐州会战总览'}).click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');
 await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('6小时');
 const phase=page.getByLabel('历史起始阶段',{exact:true});
 await phase.locator('option[value="taierzhuang"]').waitFor({state:'attached'});
 await phase.selectOption('taierzhuang');
 await page.getByLabel('生成时必须配置定时补给',{exact:true}).check();
 const approved=page.__approvedScheduleParameters;
 if(!approved)throw Error('Set page.__approvedScheduleParameters to the explicit QA input before starting');
 await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(
  '这是有历史身份的教学数值验收，不是历史部署或损失标定。下列为已明确的QA计算先验，保持数值，按当前分片逐项复核并实际通过工具写入。'+
  '先read_scenario_skill和get_scenario_basis。globals按模板提交公共参数（去掉format、phase_id、actors）；本片单位仅提交分配的actors。保留当前来源身份和required_models，定时补给必须真实写入。'+
  'goal.team使用red，目标按objectives，不在六小时强制获胜。所有参数均为未标定模型输入，说明未知的史实数字未填成事实。最终必须完整validate，回执只返回revision/configuration_hash/explanation。'+
  JSON.stringify(approved));
 page.__scheduleBuild={status:'pending',started:Date.now()};
 await page.getByTestId('generate-historical-scenario').click();
 return {started:true,scope:'Actual frontend, real DSH native tool review of explicit3actor QA inputs and AFSIM load'};
}
