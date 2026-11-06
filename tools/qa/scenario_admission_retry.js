async page => {
 page.removeAllListeners('request');page.removeAllListeners('response');
 const instruction=page.getByLabel('计算参数与推演目标需求',{exact:true});
 await instruction.fill((await instruction.inputValue())+'\n独立QA重试：严格沿原模板键集合填写。campaign_scope.remainders如果模板是空对象就保持空对象，不能给已选叶子单位新增余部条目。航空池不能写入地面fortifications。公共配置需在同一有效补丁内填完必需字段；拒收后仍用工具返回的revision，未成功时不能递增。若有input_error，按path和allowed_fields改错；不得删除史实身份、放宽规则或让宿主修正模型结果。');
 if(await page.getByTestId('fixed-parameter-inputs').locator('li').count()!==3)throw Error('Originalthreefixedairinputsrequired');
 page.__admissionBuild={status:'pending'};page.__admissionOperation=null;
 page.on('request',r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST')page.__admissionOperation=r.postDataJSON().operation_id;});
 page.on('response',async r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST')page.__admissionBuild={status:'finished',http:r.status(),request:r.request().postDataJSON(),body:await r.json()};});
 await page.getByTestId('generate-historical-scenario').click();
 return {started:true,operation_id:page.__admissionOperation,actual_model:true,additional_operator_guidance:true,
   scope:'IndependentretrywithNativefieldpathfeedbackplusstatedtemplate-keyguidance;notperformanceABtest'};
}
