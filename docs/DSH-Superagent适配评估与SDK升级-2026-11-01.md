# DSH Superagent适配评估与SDK升级

## 结论与证据范围

可以使用其设计成果，但应分为**开发维护助手**与**推演智能体编排**两条接入路线。Superagent不是AFSIM的替代品，也不补足历史人数、装备、部署或战损标定。当前不应把其完整编程Agent预设装入裁决会话。

核对的是DeepSeek发布的独立研究原型 [`dsh-superagent-prototype`](https://github.com/deepseek-ai/dsh-superagent-prototype)，提交`6337fc823ce20251c8de8085948165c81aaa701e`，包版本`0.1.0`。源码已留在本工程忽略目录`.cache/upstream/dsh-superagent-prototype/`供审阅，未启用GitHub／飞书监听。README明确说明它不是正式产品，部分论文设想尚未实现；本文按源码和编号文档判断，不把设想当接口。

上游 [`DeepSeek Harness`](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.1-rc.5) 当前发布轨道为`0.2.1-rc.5`，提交`b830ec950f`；master为`0.2.2-alpha.2`开发轨道，Node要求不同。Python SDK和自带运行时应匹配版本。PyPI现有包与源码标签应分别核对，不能将本地构建称作PyPI发布。

## 能力对照

| 原型已实现的机制 | 当前项目已有能力 | 适配决策 |
|---|---|---|
| Trigger／Ticket／Assignment、持久化输入、状态投影 | operation ID、命令修订、世界版本、任务群与分片草稿 | 保留现有身份和状态账，逐步补齐运行态；不另建一套会战世界 |
| 一工单一Executor Session、工作区隔离 | Native AgentRegistry创建／恢复单位及配置分片会话；专用DSH_HOME | 复用现有绑定；各兵团围绕同一世界快照提出命令，宿主统一校验提交 |
| 原生Inbox送达、事件唤醒、后台任务占槽 | 控制端轮询进度、Native取消、工具回执和只读观察 | 适合扩展长任务和侦察完成通知；须绑定原operation与世界版本，防止旧通知重复执行 |
| Report区分progress／waiting／ready／blocked／failed | 运行进度、失败回执、草稿校验和提交边界 | 模型一段对话结束仅表示等待校验，不等于战役结束或全部单位完成决策 |
| 监听DSH重试事件并投影模型健康状态 | 之前主要显示思考步数 | 本轮直接消费原生`llm/retry`、`llm/retry-started`和压缩事件，不自己实现重试或压缩 |
| Router／Worker各自预设与工具范围 | 每角色工具白名单、工具可见性、AFSIM执行由宿主控制 | 可复用分角色模式；保留已有领域插件，禁止编程预设直接写战局 |
| GitHub、可选飞书来源和外部回复 | 本地桌面／API教学工作台 | 独立开发助手可选；不是当前战场运行依赖，未配置外部账号或自动发消息 |

## 为何不直接加载完整bundle

原型的`cordis.patch.yml`包含GitHub来源、路由与编程Worker预设；应用层依赖Web管理、Workspace、SessionController等服务。其Worker可以运行shell和编辑文件，目标是产生代码与PR。GenTactix的`sdk-minimal`领域会话只需观察、提交结构化候选和调用受控工具。直接替换会扩大权限、引入缺失服务，并破坏物理过程统一提交的边界。

仓库开发助手若将来启用，应使用独立profile、stateDir和工作树；先通过本地检查，再按用户指令交付。它可维护资料、补测试、分析日志，不能自动认证历史真实性。推演运行时的优化则继续通过`plugins/dsh-gentactix`和SDK公开接口实现。

## 本轮落实

1. 修复目标区域地图选点：单位选择与“正在选点”分开；目标区域也能启用地图点击。放置或返回配置结束选点，修改后的草稿必须重验。保留失败浏览器证据，再用同一真实生成草稿回放验证UI。
2. 从DSH原生事件投影等待重试、重试中、压缩中、压缩失败及模型阶段结束待校验。应用阶段`phase`继续独立保存；不显示虚构百分比，不把`turn/end`当整体完成。
3. 不把供应商错误正文放进新增公开进度字段；旧序号通知不能把压缩状态回退为接收完成。上下文压缩仍由DSH管理。
4. SDK先在隔离工作树和环境构建验证，再安装到本机`wargame`环境；版本与证据见下节。旧DSH_HOME、SDK和运行时保留备份；候选运行不接触真实用户配置。
5. 生命周期探针发现一次性SDK会话不在Python角色表中、却已在DSH打开时，反事实分支重复调用`resume`失败。新增只读`/session-state`直接查询原生AgentRegistry：已打开直接分支，重启后恢复精确日志，历史缺失仍失败；不新建空父会话。先保留红例，再补三项回归，43项Harness／工具相关检查通过。

## 本机升级结果与限制

- 源码目录`/home/spikebai/gitcode/deepseek-harness`由`49a606bc5b`快进至`b830ec950f`，标签`dsh-v0.2.1-rc.5`；完整构建9/9门通过。原提交另有备份分支，已有未跟踪文件保留。
- 本机`/home/spikebai/anaconda3/envs/wargame`的SDK和`runtime-bin`均由`0.2.1rc2`升级为**`0.2.1rc5`**；SDK升级前后只有这两个发行包改变，`pip check`均保留原有lxml缺依赖提示，后续单独修复见下文。完整QA环境在其旧任务结束后也成对更新rc5；GenTactix安装程序未替换。
- 两个匹配wheel及哈希清单保存在工程忽略目录`vendor/dsh/local/0.2.1rc5/`；[安装与边界](../vendor/dsh/README.md)说明PyPI基线和本地产物的区别。**没有将不存在的PyPI版本写入默认依赖文件。**
- 实际模型通过Native工具分页核对三层任务群的准确成员、人数及指挥链，原世界未变；证据`.cache/qa/force-hierarchy-2026-10-31/model/1793521325183390534/`。这不等于完整推演验收。
- 安装后真实SDK／领域插件连接本地固定响应服务，验证精确分支继承、父子历史隔离、关闭进程后恢复且恢复本身不发请求、生成中取消和输出拒收；取消回执约**6ms**。证据`.cache/qa/dsh-sdk-rc5-installed/result.json`，不是实际模型性能指标。
- 额外用保留的rc2 SDK／运行时建立同一模型夹具会话，再用已安装rc5恢复原session ID、续写、分支和取消；旧历史保留、分支未污染父会话。证据`.cache/qa/dsh-sdk-cross-version/result-rc2.json`及`result.json`。这覆盖该会话格式的跨版本路径，不是对所有第三方插件、历史DSH数据或Windows的承诺。
- 万家岭1.3.0通过正常前端真实模型生成22单位、8个Native阶段与AFSIM装载，并进入地图；人工双边队列从前端推进一小时、22单位及人员装备账保持。详见[会战参数验收](万家岭数值先验与双边任务准入-2026-11-01.md)。
- 官方`sdk-minimal`冒烟通过；SDK测试**235通过、2失败、3平台跳过**。两失败均为“缺失插件应在initialize抛错”的exe／node用例；实际没有按预期抛错。没有删改这些测试或将其记绿。领域插件连接还由应用现有就绪文件与健康握手检查。

本地运行时构建遇到三项打包问题：legacy部署重新解析依赖、未压缩SEA注入内存失败、压缩SEA读取空文件时Node拒绝`maxOutputLength=0`。本地候选分别沿用根锁版本、启用GZip、把空文件解压上限约束为最少1字节；实际生命周期与官方minimal冒烟在修复后通过。产物约139MiB，仍超过上游PyPI单文件门限，发布校验明确失败，因此只称本地构建可安装，不称正式发布包通过。原失败日志保留。

备份目录：`/home/spikebai/.local/state/dsh-update-backups/20261101-093112/`。含原DSH_HOME、11文件哈希、旧SDK42文件及rc2匹配回滚wheel。升级后11/11 DSH保护项与68/68项目保护项不变。若需回滚，先停止使用该环境的SDK进程，再用该环境Python成对安装`rollback-wheels/*.whl`；不覆盖当前DSH_HOME或项目对局。未上传GitHub，未打包或替换GenTactix安装版。

后续全量检查发现桌面环境原有`pymavlink2.4.50`缺少已声明依赖`lxml`，升级前后的pip检查均有同一错误；单独补装`lxml6.1.3`后，清除ROS继承路径的依赖检查通过。桌面环境原本没有旧Streamlit入口的依赖，完整门禁改在具备两入口依赖、同样成对升级rc5的QA环境执行；没有为此改用户模型配置。另同步更新一个缺失父会话负例的原生状态查询替身，仍验证“缺原历史绝不新建”。失败日志与补测分别保存。

## 下一步与验收要求

最终项目完整门禁**128／128组、1419项unittest、0跳过**，逐组耗时合计489.73秒，含本轮会话、前端接点及后续[逐仓修复](多仓绑定与逐仓回执修复验收-2026-11-01.md)回归；证据`.cache/qa/wanjialing-estimates-2026-11-01/supply-binding-complete-offline-gate/`。这与上游SDK保留的两失败是不同测试范围；离线通过不能覆盖逐场历史、无中断长稳或Windows。

- 多兵团任务：以稳定历史身份、任务群修订和同一世界版本分派；命令集包含双方，错误或取消不消费已有命令。不允许各子Session独自提交时间和伤亡。
- 事件式续作：记录送达ID与接收回执；重启后可恢复，重复或过期输入不重复推进，不自动补员、合并或改写史实。
- 观察：显示实际活动会话、等待对象和工具证据。Native模型调用、AFSIM物理执行、宿主校验分别留证；离线回放不得标成实时模型验收。
- 性能：在相同模型、参数和想定上比较串行／受限并发的延迟、token、漏单率与重试，不因“多智能体”预先承诺提速。
- 逐场验收仍覆盖45场、三种用途与两种执行后端；Superagent接入不能替代连续兵力装备库存、地形过程及同范围历史校准。

主要源码入口：上游`src/core/engine.ts`、`src/app/sessions.ts`、`src/app/retry-health.ts`、`src/app/delivery.ts`、`docs/003-execution.md`、`docs/007-architecture.md`；本项目`backend/harness_engine.py`、`plugins/dsh-gentactix/index.mjs`、`backend/scenario_assembly.py`、`gentactix/force_task_execution.py`。

## 后续全局设置迁移观测（18:36:43）

上文11项保护文件未变为升级验收当时时点。后续固定输入测试期间观察到全局`settings.yaml`被改名为`.imported`，原字节与备份完全相同，两项模型设置与新headless补丁逐值一致，onboarding段仍在完整保留文档中。迁移写入进程未确认；项目SDK仍使用隔离home，没有覆盖式回滚当前全局配置。当前原路径字节检查为10／11，不能继续称11项全部未变。见[后续证据与限制](固定参数约束与DSH分片生成验收-2026-11-01.md)。
