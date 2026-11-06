/** Readonly 32-part boundary, unique labels and paging on the compiled UI. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2])),{chromium}=require('playwright-core');
const root='.cache/qa/formation-ui-2026-11-02',tag=process.argv[3],out=`${root}/${tag}`;
if(!tag||!/^[a-z0-9-]+$/.test(tag)||fs.existsSync(out))throw Error('Choose fresh evidence');
fs.mkdirSync(out);
const host='http://127.0.0.1:19214/api',checks=[],errors=[];
const save=(name,value)=>fs.writeFileSync(`${out}/${name}.json`,JSON.stringify(value,null,2));
const check=(value,label)=>{if(!value)throw Error(label);checks.push(label);};
const call=async(method,path,value)=>{
 const r=await fetch(host+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});
 if(!r.ok)throw Error(`${r.status}: ${await r.text()}`);return r.json();
};
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('pageerror',e=>errors.push(String(e)));
try{
 const source=JSON.parse(fs.readFileSync(root+'/cases.json')).narrative.source_id,base='/sessions/'+source;
 const before=(await call('GET',base+'/export')).session;save('case',{session_id:source});
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19214'});
 await page.goto('http://127.0.0.1:19216/');await page.getByRole('tab',{name:/已保存战局/}).click();
 await page.locator(`[data-session-id="${source}"] .open-battle`).click();
 await page.getByTestId('analysis-tab-forces').click();const panel=page.getByTestId('formation-conversion');
 const view=await call('GET',base+'/commands'),unit=view.units.find(u=>u.name==='第159师');
 await panel.getByLabel('实体转换单位',{exact:true}).selectOption([unit.id]);
 await panel.getByLabel('实体转换依据',{exact:true}).fill('32分队只读边界验收，固定估计参数，不保存转换或生成历史番号');
 const n=unit.personnel.committed;
 for(let i=2;i<32;i++)await panel.getByRole('button',{name:'增加分队',exact:true}).click();
 check(await panel.getByTestId('formation-allocation').count()===32,'32 allocations rendered');
 check(await panel.getByRole('button',{name:'增加分队',exact:true}).isDisabled(),'33rd allocation disabled');
 const labels=await panel.locator('.allocation input:not([type=number])').evaluateAll(nodes=>nodes.map(n=>n.value));
 save('default-labels',labels);check(new Set(labels).size===32,'all 32 default child labels unique');
 for(let i=1;i<=32;i++)await panel.getByLabel(`分队${i}投入人数`,{exact:true}).fill(String(i===1?n-31:1));
 check(await panel.getByTestId('formation-preview').isEnabled(),'exact full commitment enables preview');
 await panel.getByTestId('formation-preview').click();const preview=panel.getByTestId('formation-preview-result');
 await preview.waitFor();check((await preview.innerText()).includes('本次建议32个'),'32 candidates accepted by real API');
 const names=[];
 for(let offset=0;offset<32;offset+=8){
  await preview.getByText(`${offset+1}—${offset+8}／32`,{exact:true}).waitFor();
  const rows=await preview.locator('article b').allTextContents();check(rows.length===8,`page ${offset/8+1} returns eight rows`);names.push(...rows);
  if(offset<24)await preview.getByRole('button',{name:'下一页',exact:true}).click();
 }
 check(new Set(names).size===32,'paging visits every unique proposed identity');
 check(await preview.getByRole('button',{name:'下一页',exact:true}).isDisabled(),'last page cannot overflow');
 await preview.getByRole('button',{name:'上一页',exact:true}).click();
 await preview.getByText('17—24／32',{exact:true}).waitFor();check(true,'previous page preserves bounded view');
 await panel.getByLabel('分队32名称',{exact:true}).fill(labels[0]);
 check(await preview.count()===0,'name edit invalidates previous preview');
 check(await panel.getByTestId('formation-preview').isDisabled(),'duplicate labels blocked before preview');
 const text=await panel.innerText();check(text.includes('分队名称不可重复'),'duplicate-label guidance visible');
 await panel.getByLabel('分队32名称',{exact:true}).fill('第32分队（估计）');
 await panel.getByLabel('删除分队32',{exact:true}).click();
 check(await panel.getByTestId('formation-allocation').count()===31,'remove allocation works');
 check(await panel.getByTestId('formation-preview').isDisabled(),'removal invalidates exact total');
 await panel.getByRole('button',{name:'增加分队',exact:true}).click();
 check(await panel.getByTestId('formation-allocation').count()===32,'re-add after remove reaches cap');
 const afterLabels=await panel.locator('.allocation input:not([type=number])').evaluateAll(nodes=>nodes.map(n=>n.value));
 check(new Set(afterLabels).size===32,'re-add after removal keeps unique names');
 await panel.getByLabel('分队1投入人数',{exact:true}).fill(String(n-31));
 await panel.getByTestId('formation-preview').click();await preview.waitFor();
 await page.setViewportSize({width:900,height:1000});const box=await panel.boundingBox();
 check(box&&box.x>=0&&box.x+box.width<=901,'32-part panel fits narrow viewport');
 await page.screenshot({path:`${out}/preview-32-900.png`});
 check(JSON.stringify((await call('GET',base+'/export')).session)===JSON.stringify(before),'all capacity edits and pages leave whole session unchanged');
 check(!errors.length,'no uncaught application errors');
 save('result',{passed:true,count:checks.length,checks,errors,scope:'Compiled UI, real readonly APIs, fixed QA estimates; no model, physics or commit'});
 console.log('PASS 32-part readonly boundary',checks.length,'checks');
}catch(error){save('result',{passed:false,error:String(error),checks,errors});await page.screenshot({path:`${out}/failure.png`});throw error;}
finally{await browser.close();}
