async page => {
 page.removeAllListeners('response');
 const root='/home/spikebai/gitcode/Gentactix/.cache/qa/wanjialing-estimates-2026-11-01/browser';
 page.__estimateBuild={status:'not_started'};
 page.on('response',async r=>{
  if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST'){
   const data=await r.json();page.__estimateBuild={status:'finished',http:r.status(),id:data.id??null,body:data};
  }
 });
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19125'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('万家岭');
 await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('1小时');
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');
 const picker=page.getByLabel('会战窗口',{exact:true});
 await picker.locator('option[value="WJL-oct6-10@1.2.0"]').waitFor({state:'attached'});
 await picker.selectOption('WJL-oct6-10@1.2.0');await page.getByTestId('campaign-window-scope').waitFor();
 const evidence=page.getByTestId('campaign-window-evidence');await evidence.locator('summary').click();
 if(await page.locator('[data-estimate-actor]').count()!==22)throw Error('Missing per-unit priors');
 await page.screenshot({path:root+'/priors-1440.png'});await evidence.locator('summary').click();
 const instruction='使用窗口1.2.0进行地面多军协同的显式先验计算示例，不宣称完整史实部署或历史标定。公共参数基线已经符合以下要求，公共片读取后只提交assumptions复核说明，不要重写整份公共JSON；仍须真实update成功。单位片填写未知单位输入。'
  +'保留22个候选，不作计算分队，未核余部全部excluded_unquantified。clock=1938-10-06T00:00:00、1小时，planning_end保留窗口，area中心29.365246,115.581335、半径40km、terrain_factor1.5。'
  +'每片按window_scope.parameter_estimates范围取中等人数；位置从各自估计中心小幅错开，不把地名点当史实阵位。角色遵守prior.role；炮兵直射300m，步兵800m。全体motorized=false，步行速度3km/h；装甲0，防空0，工兵2，运输12，炮兵角色按范围最小火炮数、其他步兵火炮2；若先验工兵范围允许0的炮兵可0。随队炮弹150发/门，燃油0，材料16，备件20；疲劳10、压制0、工事10、signal80、intel_age_min10、intel_confidence80，防护0.15；展开步兵4km2，炮兵0.2km2。'
  +'粮弹覆盖一般80，106师团粮15弹25；这是计算设定，不是已核剩余口粮。到场先验可设开局可受令，逐项说明不是史实同时在场、不自动执行未来调令。'
  +'red补给节点(29.285246,115.581335)stock5000，blue(29.385246,115.581335)stock800；分类库存炮弹5000、材料500、备件100、燃油0、防空弹0；须说明本版单仓、无真实空投及内外线独立补给网络。'
  +'support_dynamics显式版本time-sustainment-1，food_work_per_hour0.7，move_factor1.5，shortage_fatigue_per_hour1，recovery_hours_per_fed_hour0.5，incapacity_after_hours48，incapacity_fraction_per_hour0.0005；工作量不是按人数或重量标定的口粮。'
  +'目标完成制，兼容goal.profile=assault,team=red,objective中心磨溪半径3km,exit在(29.365246,115.481335),deadline_turn120仅规划、required_turns2、required_survivors1；兼容campaign.objective阻援点(29.265246,115.481335)半径2km,min_force_fraction0.4。'
  +'主判据使用给定campaign_plan，不能移除方向或改ID/承担者/依赖/来源/latch。全部hold_seconds3600、not_before_seconds0；两保存目标minimum_fraction0.4；red_inner及blue_relief在磨溪中心半径3km；red_block在(29.265246,115.481335)半径2km；blue_exit在(29.365246,115.481335)半径2km；地域minimum_personnel500。'
  +'兼容campaign受降关闭，工事完整度中方5日方15、degradation_per_shell0.05；规则使用模板完整字段，bridge_enabled=false、air_support=false，不虚构空中战果。设施是无通行功能的计算汇总点。说明航空、道路、多仓和按人员标定尚缺；禁止把这些先验写成史实。';
 await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(instruction);
 page.__estimateBuild={status:'pending',started:Date.now()};
 await page.getByTestId('generate-historical-scenario').click();
 return {started:true,scope:'Real frontend->Native staged builder->AFSIM load; explicit numerical priors, not full historical acceptance'};
}
