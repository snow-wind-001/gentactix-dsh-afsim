/** Current-map replay after another client's merge, then narrow/wide readonly previews. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/formation-ui-2026-11-02',tag=process.argv[3]??'followup-1',out=`${root}/${tag}`;
if(!/^[a-z0-9-]+$/.test(tag)||fs.existsSync(out))throw Error('Choose new evidence');fs.mkdirSync(out);
const host='http://127.0.0.1:19214/api',checks=[],errors=[];
const save=(n,v)=>fs.writeFileSync(`${out}/${n}.json`,JSON.stringify(v,null,2));
const check=(v,s)=>{if(!v)throw Error(s);checks.push(s);};
const call=async(method,path,value)=>{const r=await fetch(host+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});if(!r.ok)throw Error(await r.text());return r.json();};
const get=p=>call('GET',p);const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
const appUrl=process.env.FORMATION_UI_URL??'http://127.0.0.1:19215/';
page.on('pageerror',e=>errors.push(String(e)));
try{
    const original=JSON.parse(fs.readFileSync(root+'/cases.json')).narrative;
    const source='/sessions/'+original.source_id,v=await get(source+'/commands');
    const created=await call('POST',source+'/commands/open-branch',{expected_turn:v.turn,revision:v.revision,world_version:v.world_version});
    const sid=created.session_id,base='/sessions/'+sid;save('case',{session_id:sid});const before=(await get(base+'/export')).session;
    await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19214'});await page.goto(appUrl);
    await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
    const q=await get(base+'/commands'),unit=q.units.find(u=>u.name==='第159师'),initialIds=new Set(q.units.filter(u=>u.present).map(u=>u.id));
    await page.getByTestId('command-toggle').click();await page.getByLabel('单位名单（含无坐标单位）').selectOption(unit.id);
    await page.getByTestId('analysis-tab-forces').click();const panel=page.getByTestId('formation-conversion');
    await panel.getByLabel('实体转换单位',{exact:true}).selectOption([unit.id]);await panel.getByLabel('实体转换依据',{exact:true}).fill('独立客户端后续合兵时的原请求查询验收，不是历史命令');
    await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').waitFor();
    let drop=true;const requests=[];
    await page.route('**/force-organization/conversion-commit',async route=>{
        requests.push(JSON.parse(route.request().postData()));
        if(drop){drop=false;const response=await route.fetch();check(response.status()===200,'original split saved before injected loss');await route.abort('failed');}
        else await route.continue();
    });
    await panel.getByTestId('formation-confirm').click();await panel.getByText(/提交结果待核实/).waitFor();
    const split=await get(base+'/commands'),children=split.units.filter(u=>u.present&&!initialIds.has(u.id));
    check(children.length===2,'first split produced two actual actors');const organization=await get(base+'/force-organization');
    const merge={expected_turn:split.turn,revision:split.revision,world_version:split.world_version,organization_revision:organization.revision,
        kind:'merge',unit_ids:children.map(u=>u.id),assumption:'显式模拟另一客户端在响应丢失后合并分队，验证当前映射'};
    const preview=await call('POST',base+'/force-organization/conversion-preview',merge);
    const merged=await call('POST',base+'/force-organization/conversion-commit',{...merge,view_version:preview.view_version,commit_id:crypto.randomUUID().replaceAll('-','')});
    const currentIds=[...new Set(Object.values(merged.conversion_result.current_command_map).flat())];check(currentIds.length===1,'other client merged into one current actor');
    await panel.getByTestId('formation-retry').click();await panel.getByTestId('formation-saved').waitFor({state:'attached',timeout:60000});
    check(requests.length===2&&JSON.stringify(requests[0])===JSON.stringify(requests[1]),'old original request replayed unchanged after later conversion');
    const current=(await get(base+'/export')).session;
    check(current.war_state.formation_registry.transactions.length===2,'late retry never repeats split');
    check(await page.getByLabel('单位名单（含无坐标单位）').inputValue()===currentIds[0],'selected source follows current merged identity');
    const buttons=panel.locator('[data-current-conversion-unit]');check(await buttons.count()===1,'receipt shows one current unit rather than two original split IDs');
    check(await buttons.first().getAttribute('data-current-conversion-unit')===currentIds[0],'receipt current actor matches authoritative identity');
    check(await page.getByTestId('conversion-selection').count()===0,'no obsolete multiple-choice prompt');
    save('expected-cold',current);
    for(const width of [1440,900]){
        await page.setViewportSize({width,height:1000});await page.getByTestId('analysis-tab-forces').click();
        // Opening the same tab twice toggles it. Ensure this existing drawer is open.
        if(!await panel.isVisible())await page.getByTestId('analysis-tab-forces').click();
        const beforePreview=(await get(base+'/export')).session;
        await panel.getByLabel('实体转换方式',{exact:true}).selectOption('split');await panel.getByLabel('实体转换单位',{exact:true}).selectOption(currentIds);
        const sourceUnit=(await get(base+'/commands')).units.find(u=>u.id===currentIds[0]);
        const a=Number(await panel.getByLabel('分队1投入人数').inputValue()),b=Number(await panel.getByLabel('分队2投入人数').inputValue());
        check(a+b===sourceUnit.personnel.committed&&sourceUnit.personnel.current<sourceUnit.personnel.committed,'allocations use original commitment and preserve existing losses');
        await panel.getByLabel('分队1投入人数').fill('1');check(await panel.getByTestId('formation-preview').isDisabled(),'invalid allocation sum cannot request preview');
        await panel.getByLabel('分队1投入人数').fill(String(a));await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').waitFor();
        await panel.getByText('分类装备与绝对库存守恒',{exact:true}).click();
        const box=await panel.boundingBox();check(box&&box.x>=0&&box.x+box.width<=width+1,`${width}px panel within viewport`);
        await page.screenshot({path:`${out}/preview-${width}.png`});
        check(JSON.stringify((await get(base+'/export')).session)===JSON.stringify(beforePreview),`${width}px preview and invalid edits never mutate world or tasks`);
    }
    check(!errors.length,'no uncaught application errors');save('result',{passed:true,checks,count:checks.length,errors,application_url:appUrl,
        scope:'Explicit second-client conversion and response-loss injection, real APIs and normal UI; no model or physical execution'});
    console.log('PASS current identity replay and responsive preview',checks.length,'checks');
}catch(error){save('result',{passed:false,error:String(error),checks,errors});await page.screenshot({path:`${out}/failure.png`});throw error;}
finally{await browser.close();}
