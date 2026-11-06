async page=>{
 const sid='09ce11fb7fe2',base='http://127.0.0.1:19097/api/sessions/'+sid;
 await page.addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:19097'};});
 await page.goto('http://127.0.0.1:19086');await page.evaluate(id=>localStorage.setItem('gentactix-session',id),sid);
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.locator('.nato-marker').first().waitFor();
 const count=await page.locator('.nato-marker').count();if(count!==6)throw Error('Expected six execution markers, got '+count);
 if(await page.getByTestId('history-replay').count())throw Error('Open history simulation rendered as strict replay');
 await page.getByTestId('analysis-tab-forces').click();await page.getByTestId('force-organization').waitFor();
 const r=await page.request.get(base+'/force-organization');if(!r.ok())throw Error(await r.text());const org=await r.json();
 if(org.nodes.length!==31||org.groups.length!==1||org.groups[0].member_ids.length!==2)throw Error('Reference and execution tree do not match');
 const parent=page.locator('[data-force-node="ww2.cn.army4"]');
 if(!(await parent.innerText()).includes('已部署下级汇总')||!(await parent.innerText()).includes('未列余部不计入'))throw Error('Partial parent incorrectly presented as entire army');
 const receipts=await page.request.get(base+'/unit-decisions?start_turn=18&end_turn=18&limit=100');const data=await receipts.json();
 if(data.items.length!==6||data.items.filter(x=>x.task_context).length!==2)throw Error('Missing final group decision receipts');
 await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'.cache/qa/wanjialing-sources-2026-10-31/browser/open-six-1440.png'});
 return {passed:true,session_id:sid,execution_markers:count,reference_nodes:org.nodes.length,task_members:2,decision_receipts:6,partial_totals_labeled:true};
}
