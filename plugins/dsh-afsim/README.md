# GenTactix DSH–AFSIM 领域插件

复用 DSH/Cordis 原生工具注册、会话、事件与 MCP 客户端。DSH 负责决策控制，AFSIM 负责运动及已登记的教学规则计算，GenTactix 负责权威检查点、输入/结果校验与现有前端。本插件不另建模型或 MCP 传输层，也不使用 PTC。

DSH独立过程的engine复用宿主插件原生`preview_turn_effects`与`submit_turn_report`：从Agent公开会话事件选取预览证据，核验完整战报候选，在运行正常完成后才沿宿主事务提交。最后自由文本不再承载Native数值结果；工具不会执行AFSIM、扣物资或提前提交。AFSIM角色、问答及分析角色不获得该报告工具。旧JSON兼容仍严格校验，报告指纹通过不代表语义或历史效能通过。见[实际验收和未完成项](../../docs/Native战报候选与JSON拒收修复验收-2026-11-01.md)。

## 文件与依赖

- `index.mjs`：Cordis 插件入口；加载同级目录下的 `dsh-gentactix` 宿主插件。
- `protocol.mjs`：分页观察和受控原生 MCP 调度适配器。
- `../../tools/afsim/launch.py`：项目内启动与环境隔离。
- `../../backend/afsim_*.py`：宿主侧状态观察、场景编译、回合与只读分支适配。
- `../../vendor/afsim/afsim-mcp`：固定版本的上游 MCP 服务，标准库实现，无额外 pip 依赖。
- `../../vendor/afsim/afsim-skill`：语法、模板和错误索引参考；不代替执行内核。
- DSH SDK/runtime 版本见 `requirements-dsh.txt`；基础宿主依赖见 `requirements.txt`。

这是 GenTactix 的宿主扩展，需要同版本后端的控制桥、状态及命令接口；不能将单个 `index.mjs` 复制到任意 DSH 安装后就当作完整推演应用。

会战目标图与多兵种契约启用时，单位观察的`participation`为宿主参与状态。退出／重返使用现有移动命令、候选预览和执行回执；后方仍有实际位置、伤损和库存，可被攻击，不是场外补算或满编重置。模型不写`unit_participation`登记；参考[同世界参与状态验收](../../docs/单位参与状态与退出重返接入验收-2026-11-01.md)。

## 安装和使用

1. 将有使用权限的 AFSIM 2.9.0 Windows 运行目录放入 `vendor/afsim/local/afsim/runtime/afsim-2.9.0-win64/`，确认 `bin/mission.exe` 存在。
2. Windows 原生执行无需 Wine。当前 Ubuntu 验证使用同项目 `local/afsim/compat/` 的 Wine；复制兼容层到新 Linux 机器后，运行 `python tools/afsim/launch.py --prepare` 创建该机器的专用 prefix。
3. 执行 `python tools/afsim/launch.py --status`。文件存在不表示已运行验证；创建战局时后端会做真实装载检查。
4. 在“确认想定参数”选择历史战役回溯分析、历史战局推演或合成教学演习。合成演习读取史实参考，经DSH skill生成、地图编辑和AFSIM装载验证后创建；不再自动用通用六编组代替历史战局。旧存档保持原后端。
5. 后端仅为本项目 DSH home 生成 MCP overlay，原生客户端连接 vendored stdio 服务；不更改用户全局 DSH 配置。完整人工命令批次跳过模型，其他批次只向模型提供有限观察及命令格式。

冻结后端可通过 `GENTACTIX_PROJECT_ROOT` 指向包含私有运行目录的项目根目录。`--afsim-mcp` 与 `--afsim-mission-proxy` 是包内进程入口，不是新的服务协议。

## 证据与边界

执行证据记录 AFSIM 版本、进程、原生调度 ID、退出码、相对秒及实体回传数。坐标缺失的单位留在账本中，不虚构外部位置；失败或取消不提交主战局。逐单位回执、轨迹及只读命令对照沿用现有界面。

当前为 **AFSIM 地理运动 + 原生执行固定局部教学规则**，不回退Python教学结算。AJ18/AJ19另有目标航空支援：选择敌方单位，实际航路飞行、目标复核、合成防空/打击与返场，航空油弹和飞机账独立计算；近期事件及原生地面/空袭归因回传给DSH和原前端。旧版无目标支援的补给干扰不等于航空任务。参数及缺口见[团级装备与航空建模](../../docs/AFSIM团级装备与航空建模.md)。

未标定 DEM/道路、射界遮挡、弹道、真实武器杀伤、通信和历史伤亡模型。45 个目录条目的装载验收采用 20 个已有教学初态和 25 个明确标注的合成初态，不代表 45 场历史编制与战损已完成校准。固定教学初态也是教学抽象。

## 具名历史航空资源（未发布）

历史航空不再被当作地面步兵或固定红方飞机池。`historical-units` skill按所选阶段填写独立`aviation`参数，宿主绑定冻结身份与来源；多航空池用`air_pool`选择，双方分别守恒。现有WSF航空模块执行原生航路、防空、目标复核和返场。关闭AFSIM时，DSH另交任务过程及油弹余额，由应用校验，明确标注模型估计，不生成AFSIM回执。湘西仅新增4月下旬洞口方向部分身份，缺载库存仍null，不是精确历史任务回放。详见[来源、实现和验证边界](../../docs/历史航空资源绑定与双引擎验证-2026-10-28.md)。

## 只读累计账

`get_afsim_changes`默认返回逐轮明细，可选`mode=aggregate`按有变化的单位汇总人员／装备端点、火力、位移及分类到货。两种模式均需沿`next_args`读完，版本改变从0重读；时间范围和模式不能混页。未知端点、缺载回执和缺轮不会补0；装备维修不算新增毁损，净库存差不是发射量。

明细默认最近一轮，累计模式默认自首轮到当前。`since_turn`排除下界、`through_turn`包含上界：第1—8轮用`since_turn=0, through_turn=8`，填1会漏首轮。响应`window`明确首个请求轮次、是否含首轮及`full_session`；局部累计不能称为全局总量。保留显式范围及`next_args`，不自动扩大调用者选定的局部窗口。

`full_session`说明请求范围，不保证原始记录完整；仍需核对`coverage.missing_turn_count`和各字段的`missing_receipts`。翻页将`next_args`对象直接作为下一次参数，保留`view_version`。领域校验失败通过UTF-8 JSON返回，原生插件保留具体错误，失败查询不会修改操作快照。

`artillery_shells_fired`仅统计间瞄炮弹；原始`shots`混有直射周期，不能当作统一弹数。自身火力时长不等于目标承受火力或战役历时。累计查询只是账目归并，不能证明因果或历史效能。见[原生事件、载荷与界面复测](../../docs/DSH累计账观察与表格复核-2026-10-28.md)。

## 打包与验证

```bash
python tools/build_afsim_bundle.py
python tools/build_linux.py --backend-only
python verify_afsim_components.py
python verify_afsim_world.py
python verify_afsim_backend.py
python verify_afsim_native.py
python verify_afsim_air.py
python verify_afsim_summary.py
python tools/qa/afsim_air_audit.py --live # 原生航空及真实DSH读取，产生模型用量
node tools/qa/afsim_plugin.mjs
python tools/qa/afsim_catalog.py          # 需要真实 AFSIM，不调用模型
python tools/qa/afsim_live_workflow.py    # 真实模型与 AFSIM，会产生模型用量
```

适配器包只包含本项目代码和 MIT 参考组件；AFSIM 本体、Wine prefix、模型配置、密钥、对局与运行日志不进入该包。`local/` 内的 AFSIM 源码、程序及资料受原分发条件约束，不能因辅助组件为 MIT 而公开发布。

参考：[DSIAC](https://dsiac.dtic.mil/models/afsim/)、[afsim-skill](https://github.com/qingzhoupro/afsim-skill)、[AFSIM_MCP](https://github.com/Yookio-Z/AFSIM_MCP)。

## 严格史料事件重现

`simulation_mode=replay` 为历史战役回溯分析的来源帧执行；禁止模型生成状态、开放战斗规则或命令干预。45项共266个事件帧，地名参考点不是部队部署。完整历史战局推演仍缺分期初态和专用机制，见[逐场过程审计](../../docs/历史过程逐场审计-2026-10-27.md)。CA模板作为兼容规则保留，不能直接代表完整历史会战。

## 史实基础派生与项目skill

`skills/historical-scenario/SKILL.md`定义结构化配置流程，按需读取上游`afsim-skill`模板约束。通过现有Cordis插件注册`read_scenario_skill`、`get_scenario_basis`和`validate_scenario_configuration`，使用DSH原生工具事件与角色预算；不是新增模型传输、PTC或任意shell执行。

DSH只编辑编组配置，版本和不可变史料摘要由宿主绑定。参数经`combined_arms.configure`校验，由原有封闭编译器生成WSF并真实装载。草稿保存在会话目录旁的`scenario-drafts/`，尚未创建战局；地图或数值编辑后必须重新验证。每方1–12个编组、五类已登记装备和库存可改；源码、资料卡和历史未知项保持只读。

创建时校验草稿、配置摘要和当前规则一致性；旧模型草稿需重新验证。构建证据、来源单位与估计标识进入存档。新建演习用的不是已审订完整历史部署，局部位置、人数及武器系数仍为演习假设。DSH生成可能需要多次推理，不能把AFSIM装载耗时当成整体生成耗时。

可选作战区边界`operation-boundary-1`区分原物理世界与其中的作战区域；实际出入登记直线通路后，场外状态为`offmap`，不是旧`reserve`。单位与资源仍保存在同一世界，不转移到聊天上下文。摘要沿现有观察工具提供，完整通路沿`get_afsim_observation(detail=true，按所选单位阵营返回通路)`读取；模型不能直接写参与登记。新配置需明确启用并验证，旧局不迁移。
