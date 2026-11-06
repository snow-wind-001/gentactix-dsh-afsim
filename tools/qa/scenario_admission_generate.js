async page => {
 if(await page.getByLabel('编制范围',{exact:true}).inputValue()!=='campaign')throw Error('ExplicitJizhongcampaignrequired');
 const basis=page.__admissionBases.at(-1).body;
 if(basis.initial.profile_id!=='AJ15-jizhong'||Object.keys(basis.configuration_template.actors).length!==34)throw Error('ExpectedJizhong34identitybasis');
 page.__admissionBuild={status:'pending'};
 page.on('request',r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST')page.__admissionOperation=r.postDataJSON().operation_id;});
 page.on('response',async r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST')
   page.__admissionBuild={status:'finished',http:r.status(),request:r.request().postDataJSON(),body:await r.json()};});
 await page.locator('#draft-step').selectOption('6小时');
 const editor=page.getByTestId('fixed-parameter-inputs');await editor.locator('summary').click();
 for(const [path,value] of [[['aviation','ww2.jp.flight29','initial','committed'],4],[['aviation','ww2.jp.flight29','initial','ordnance'],8],[['aviation','ww2.jp.flight29','initial','fuel'],16]]){
   const field=basis.fixed_parameter_fields.find(f=>JSON.stringify(f.path)===JSON.stringify(path));if(!field)throw Error('Missingairfixedfield');
   await page.getByLabel('固定参数配置对象',{exact:true}).selectOption(field.group);
   await page.getByLabel('固定参数数值项目',{exact:true}).selectOption(JSON.stringify(path));
   await page.getByLabel('固定参数指定数值',{exact:true}).fill(String(value));await page.getByTestId('add-fixed-parameter').click();
 }
 await page.getByLabel('计算参数与推演目标需求',{exact:true}).fill(
   'QA会战准入验证，不声称完整史实重演或已标定效能。必须保留全部34个地面历史身份、行政隶属及第29独立飞行队独立资源。'
   +'开局建议1942-05-01T00:00:00，规划边界1942-06-21T00:00:00，6小时一轮，按目标完成。'
   +'保留来源已核/未知和累计参战之别；地面人数、分类装备和分散部署按各单位层级作明确未标定的建模估计，双方部署不得全部同点。'
   +'按军分区及其所属团/地区队与日军各方向建立可运行的到场计划、双边可计算目标与足够长窗口保障，未知余部登记未投入，不能声称完整父级。'
   +'航空固定4架、8弹药工作量、16燃油工作量是QA输入，绝非1942史实库存；availability.start建议1942-05-02T00:00:00，end=null持续可用。'
   +'必须填写air-availability-1估计依据，保留air_support=true用于后续核查未入场不可出动；航空入场点也只是计算估计。'
   +'无需网络取史或运行shell；完整参数沿Native分片工具更新，核对工具错误后修正。');
 await page.getByTestId('generate-historical-scenario').click();
 return {started:true,operation_id:page.__admissionOperation,actual_frontend:true,actual_model_generation:true,expected_ground_identities:34,expected_aviation_pools:1,
   fixed_air_fields:3,scope:'ExplicitcumulativecampaignQAandtemporalairinput;notfullhistoricalprocess'};
}
