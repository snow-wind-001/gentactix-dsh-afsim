/** Actual two-backend UI conversions; explicit response-loss/staleness injection. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/formation-ui-2026-11-02',tag=process.argv[3]??'workflow-1',out=`${root}/${tag}`;
if(!/^[a-z0-9-]+$/.test(tag)||fs.existsSync(out))throw Error('Choose a new evidence tag');
fs.mkdirSync(out);const api='http://127.0.0.1:19214/api';
const call=async(method,path,value)=>{const r=await fetch(api+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});if(!r.ok)throw Error(`${r.status}: ${await r.text()}`);return r.json();};
const get=path=>call('GET',path);const save=(name,value)=>fs.writeFileSync(`${out}/${name}.json`,JSON.stringify(value,null,2));
const appUrl=process.env.FORMATION_UI_URL??'http://127.0.0.1:19215/';
const all=w=>[...w.red_units,...w.blue_units];
const totals=w=>all(w).reduce((a,u)=>{for(const k of ['committed','current','casualties','noncombat_losses'])a[k]=(a[k]??0)+(u.personnel[k]??0);return a;},{});
const browser=await chromium.launch({channel:'chrome',headless:true}),checks=[],errors=[],cases={};
let activePage;
const check=(v,label)=>{if(!v)throw Error(label);checks.push(label);};
async function open(page,sid){
    await page.goto(appUrl);await page.getByRole('tab',{name:/已保存战局/}).click();
    await page.locator(`[data-session-id="${sid}"] .open-battle`).click();await page.getByTestId('map-unit-locator').waitFor();
}
async function tasks(base,count){
    const a=await get(base+'/force-organization/tasks');check(a.rows.length===1,'one original persistent task');
    const m=await get(base+'/force-organization/tasks?kind=members&task_id='+a.rows[0].id);
    check(m.rows.length===count&&m.rows.every(r=>r.executions===1),'task deliveries inherited individually without double-counting');
}
try{
    const sources=JSON.parse(fs.readFileSync(`${root}/cases.json`));
    for(const engine of ['narrative','afsim']){
        const sourceBase='/sessions/'+sources[engine].source_id,q=await get(sourceBase+'/commands');
        const b=await call('POST',sourceBase+'/commands/open-branch',{expected_turn:q.turn,revision:q.revision,world_version:q.world_version});
        const sid=b.session_id,base='/sessions/'+sid;cases[engine]={session_id:sid};save('cases',cases);
        const before=(await get(base+'/export')).session;save(engine+'-before',before);
        const page=await browser.newPage({viewport:{width:1440,height:1000}});
        activePage=page;
        page.on('pageerror',e=>errors.push(String(e)));
        await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19214'});
        await open(page,sid);const commands=await get(base+'/commands'),original=commands.units.find(u=>u.name==='第159师');
        await page.getByTestId('command-toggle').click();await page.getByLabel('单位名单（含无坐标单位）').selectOption(original.id);
        await page.getByTestId('unit-action').selectOption('move');
        await page.getByTestId('analysis-tab-forces').click();
        let panel=page.getByTestId('formation-conversion');await panel.waitFor();
        await panel.getByLabel('实体转换单位',{exact:true}).selectOption([original.id]);
        await panel.getByLabel('实体转换依据',{exact:true}).fill('实际前端软件验收，分队分配为估计，不是历史改编命令');
        await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-preview-result').waitFor();
        const afterPreview=(await get(base+'/export')).session;
        check(JSON.stringify(afterPreview)===JSON.stringify(before),engine+' preview is whole-session readonly');
        await panel.getByLabel('分队1名称',{exact:true}).fill('前端甲（估计）');
        check(await panel.getByTestId('formation-confirm').count()===0,engine+' edits invalidate preview');
        await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').waitFor();
        const posts=[];let dropped=false,firstStatus;let firstDone;
        const firstResponse=new Promise(resolve=>{firstDone=resolve;});
        await page.route('**/force-organization/conversion-commit',async route=>{
            posts.push(JSON.parse(route.request().postData()));
            if(!dropped){
                dropped=true;const response=await route.fetch();firstStatus=response.status();
                save(engine+'-injected-response',{status:firstStatus,...(firstStatus!==200?{body:await response.text()}:{})});
                if(firstStatus===200)await route.abort('failed');else await route.fulfill({response});
                firstDone();
            }
            else await route.continue();
        });
        await panel.getByTestId('formation-confirm').click();
        await firstResponse;check(firstStatus===200,engine+' fault injected only after real save');
        await panel.getByText(/提交结果待核实/).waitFor();
        const splitSaved=(await get(base+'/export')).session;
        check(all(splitSaved.war_state).length===7,engine+' server saved one split before response loss');
        check(splitSaved.war_state.formation_registry.transactions.length===1,engine+' exactly one conversion despite uncertain UI');
        check(JSON.stringify(totals(splitSaved.war_state))===JSON.stringify(totals(before.war_state)),engine+' personnel accounts conserved');
        if(engine==='afsim'){
            await page.reload();await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
            await page.getByTestId('analysis-tab-forces').click();panel=page.getByTestId('formation-conversion');
            await panel.getByTestId('formation-pending').waitFor();check(true,'pending original request survives page reload');
        }
        await panel.getByTestId('formation-retry').click();await panel.getByTestId('formation-saved').waitFor({state:'attached',timeout:60000});
        check(posts.length===2&&JSON.stringify(posts[0])===JSON.stringify(posts[1]),engine+' byte-equivalent request and commit_id reused');
        const split=(await get(base+'/export')).session;save(engine+'-split',split);await tasks(base,2);
        check(split.war_state.formation_registry.transactions.length===1,engine+' exact retry creates no second conversion');
        const originalIds=new Set(commands.units.filter(u=>u.present).map(u=>u.id));
        const splitCommands=await get(base+'/commands'),children=splitCommands.units.filter(u=>u.present&&!originalIds.has(u.id)&&u.team==='red');
        check(children.length===2,engine+' both current split actors exposed');
        if(engine==='narrative'){
            const choice=page.getByTestId('conversion-selection');await choice.waitFor();
            check(await choice.getByRole('button').count()===2,'multiple successors require explicit choice');
            await choice.getByRole('button').first().click();check(await page.getByTestId('unit-action').inputValue()==='hold','old unsaved move draft cleared');
        }
        for(const child of children){
            if(await page.getByTestId('command-panel').isVisible())await page.getByRole('button',{name:'收起指挥面板',exact:true}).click();
            const locator=page.getByTestId('map-unit-locator');await locator.getByRole('button').first().click();
            await page.locator('[data-locate-unit]').filter({hasText:child.name}).click();
            check(await page.getByLabel('单位名单（含无坐标单位）').inputValue()===child.id,engine+' overlapping child selectable: '+child.name);
        }
        await page.getByTestId('analysis-tab-forces').click();panel=page.getByTestId('formation-conversion');
        await panel.getByLabel('实体转换方式',{exact:true}).selectOption('merge');
        await panel.getByLabel('实体转换单位',{exact:true}).selectOption(children.map(u=>u.id));
        await panel.getByLabel('实体转换依据',{exact:true}).fill('同地同根分队合兵的软件验收，保留实际伤损和任务');
        await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').click();
        await panel.getByTestId('formation-saved').waitFor({timeout:60000});
        const merged=(await get(base+'/export')).session;save(engine+'-merged',merged);await tasks(base,1);
        check(JSON.stringify(merged.command_state.unit_agents)===JSON.stringify(before.command_state.unit_agents),engine+' UI conversion preserves enabled Native unit policy');
        check(all(merged.war_state).length===6&&merged.war_state.formation_registry.transactions.length===2,engine+' two UI conversions leave six actors');
        check(JSON.stringify(totals(merged.war_state))===JSON.stringify(totals(before.war_state)),engine+' merge preserves losses');
        check(JSON.stringify(merged.war_state.simulation_clock)===JSON.stringify(before.war_state.simulation_clock),engine+' UI conversion never advances time');
        check(JSON.stringify(merged.history)===JSON.stringify(before.history)&&JSON.stringify(merged.trajectory)===JSON.stringify(before.trajectory),engine+' no past reports or trajectories rewritten');
        const splitIds=new Set(splitCommands.units.filter(u=>u.present).map(u=>u.id));
        const qc=await get(base+'/commands'),current=qc.units.find(u=>u.present&&u.team==='red'&&!splitIds.has(u.id));
        check(!!current,engine+' merged current identity exposed');
        await panel.getByLabel('实体转换方式',{exact:true}).selectOption('split');await panel.getByLabel('实体转换单位',{exact:true}).selectOption([current.id]);
        await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').waitFor();
        const fields=['id','unit_id','action','duration','destination','target_id','air_pool','end_turn','participation'];
        await call('PUT',base+'/commands',{expected_turn:qc.turn,revision:qc.revision,world_version:qc.world_version,control_team:qc.control_team,director:qc.director,no_fire:qc.no_fire,
            unit_agents:qc.unit_agents,intent:'故意修改命令修订以验证过期转换拒收',orders:qc.orders.map(o=>Object.fromEntries(Object.entries(o).filter(([k])=>fields.includes(k))))});
        await panel.getByTestId('formation-confirm').click();await panel.getByText(/本请求已明确拒收/).waitFor();
        check((await get(base+'/export')).session.war_state.formation_registry.transactions.length===2,engine+' stale commit rejected with no extra conversion');
        check(JSON.stringify((await get(base+'/commands')).unit_agents)===JSON.stringify(qc.unit_agents),engine+' stale-version fault leaves Native policy unchanged');
        save(engine+'-posts',posts);await page.screenshot({path:`${out}/${engine}-final.png`});
        save(engine+'-expected-cold',(await get(base+'/export')).session);
        await page.close();
    }
    check(!errors.length,'no uncaught application errors');save('result',{passed:true,checks,count:checks.length,errors,cases,application_url:appUrl,
        scope:'Real normal UI/API with explicit network/staleness faults; no LLM or physics execution in this probe, not history acceptance'});
    console.log('PASS full runtime conversion UI',checks.length,'checks');
}catch(error){save('result',{passed:false,error:String(error),checks,errors,cases});if(activePage)await activePage.screenshot({path:`${out}/failure.png`});throw error;}
finally{await browser.close();}
