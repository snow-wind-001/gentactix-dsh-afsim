# AFSIM MCP

本项目是一个本地 MCP（Model Context Protocol）服务器，让大模型能真正跑起 AFSIM
（Advanced Framework for Simulation, Integration, and Modeling）仿真并读懂结果。

**只有 4 个工具。** 不是一个功能齐全的想定编辑器，而是一层薄薄的、专门补上
模型自身做不到的那几件事的垫片。

## 边界：工具归工具，知识库归知识库

这个 MCP 只做两件事，两件事都不含判断：

**一、AFSIM 知识库（`core/knowledge/`）** — 只读 AFSIM 安装目录，只报告里面有什么。
不含任何作者编写的规则，AFSIM 升级后可以整体重新生成。

**二、工具（`core/runtime|validation|analysis`）** — 执行能力。薄，不含知识。

### 分层与依赖方向

```
core/knowledge/     事实：从安装目录提取           不含判断
  ├ source.py         归一化读取（CRLF 会静默吞声明）
  ├ type_index.py     类型命名空间
  └ mission_grammar.py  mission 输出的语法

core/policy.py      判断：哪些事实算失败         全部具名、可覆盖

core/runtime.py     执行器：起进程
core/validation.py  执行器：跑 + 解析
core/analysis.py    执行器：evt → 指标
core/results.py     执行器：运行记录

core/server.py      配置解析与 JSON-RPC 分发
tools/              MCP 接口：模型答不了的问题
transport/stdio.py  传输
```

**依赖严格单向，下层不导入上层**（`tests/test_layers.py` 会检查）。
一个事实不能悄悄变成判断，一个底层模块不能悄悄依赖上层。

### 什么进知识库，什么不进

| 进知识库 | 不进知识库 |
|---|---|
| 这台机器上有哪些 `platform_type` | 什么样的防空部署是合理的 |
| mission 的报错长什么样 | 这个想定该怎么设计 |
| `.evt` 怎么分类 | Pk 意味着什么、要不要追求 |

判据：**能从 AFSIM 安装里提取出来的进，靠经验猜的不进。**

这不是理论。这个仓库里两件"嵌知识"的事成功、两件失败：

- **成功**：类型目录、错误语法。都是从 mission 真正读取的字节里提取的。
  装上之后模型不再编造 `AUTO_BLUE_FIGHTER_AIR`。
- **失败**：关键词推断层、想定模板。都是作者根据经验猜的。结果是提示词写
  "不要任何飞机"，照样生成空中战斗机，平台类型只有 `icon` + `mover`。

### 4 个工具，每个对应一个模型答不了的问题

| 工具 | 模型为什么答不了 |
|---|---|
| `afsim_types` | `platform_type` 命名空间是封闭的，编错 mission 直接拒绝。 |
| `run_mission` | 编译、实例化、运行在 AFSIM 里是一次 `mission.exe` 调用，报错格式必须从真实输出解析。 |
| `analyze_run` | KPI 和时间线来自数 MB 的 `.evt`，模型数不准。 |
| `launch_afsim_tool` | 启动 GUI 工具。 |

每个工具都要能回答"模型为什么不能自己问这个问题"。
按这条规则 `list_demos` 站不住（68 个目录，`ls` 一下就行），已经删掉。

### 判断是显式的

`core/policy.py` 里的每条规则都具名、可从参数覆盖：

```jsonc
// 一份"跑了但什么都没发生"的仿真，默认判失败
{ "ok": false, "policy": { "inert_is_failure": true, ... },
  "problems": ["simulation ran but produced no activity: ..."] }

// 不认同这个判断的调用方可以覆盖
run_mission { scenario_file: "...", inert_is_failure: false }
// → problems 变 caveats，ok 变 true
```

之前这些判断埋在 `validation.py` 里，读起来像是 mission 自己说的。

## 前置条件

- Windows
- Python 3.10+
- 已安装 AFSIM（`mission.exe` 等）。类型目录从 AFSIM 自带的 demos 索引而来。

服务只依赖 Python 标准库，**不需要安装 `mcp` 包**：`transport/` 内置了完整的
JSON-RPC / MCP stdio 实现。

## 快速开始

```bash
python configure_mcp.py
```

脚本会询问 AFSIM 根目录、工程目录、demos 目录和 bin 目录，写入
`%USERPROFILE%\.afsim_mcp\config.json`，并输出客户端配置片段。

| 环境变量 | 作用 |
|---|---|
| `AFSIM_ROOT` | AFSIM 安装根目录 |
| `AFSIM_PROJECT_ROOT` | 你的工程目录 |
| `AFSIM_DEMOS_DIR` | demos 目录（类型目录的数据源） |
| `AFSIM_BIN` | `mission.exe` 等可执行文件所在目录 |
| `AFSIM_MCP_CONFIG_DIR` | 配置文件所在目录，客户端只需传这一个 |
| `AFSIM_MCP_STATE_DIR` | 状态目录（类型目录缓存、运行记录） |

客户端配置形如：

```json
{
  "mcpServers": {
    "afsim": {
      "command": "python",
      "args": ["<仓库路径>/transport/stdio.py"],
      "env": { "AFSIM_MCP_CONFIG_DIR": "C:\\Users\\你\\.afsim_mcp" }
    }
  }
}
```

## 工作流

```
1. afsim_types          查真实的 platform_type（模型必须选，不能编）
2. （模型自己写 AFSIM 文本到工程目录）
3. run_mission          跑 + 校验，拿到 file:line:column 的真实报错
4. 按报错改文本，再跑
5. analyze_run          出战斗报告与 KPI
```

### 第 1 步：类型目录

AFSIM 有**两个封闭的类型命名空间**，两个都被索引了（2.9.0 实测）：

| 层级 | 数量 | 说明 |
|---|---|---|
| `platform_type` | 657（224 个含传感器或武器） | 完整的平台类型，含运动器/传感器/武器/处理器清单 |
| 组件类型 | 535 | `sensor` / `weapon` / `mover` / `processor` / `comm` / `filter` |
| AFSIM 内置库类 | 88 | `WSF_*`，编译进 DLL，从不在 demos 里声明，但确实存在 |

区分方法是缩进：**顶格**的 `sensor aesa WSF_RADAR_SENSOR` 是类型定义，
**缩进**的 `sensor rdr1 aesa` 是平台内的实例（实例 `rdr1`，类型 `aesa`）。

```
afsim_types(domain="air")
  → AIR_MOVER_FIGHTER, DCA, ESCORT, HVAA, LTE_FIGHTER, SIX_DOF_FIGHTER, SOJ ...

afsim_types(name="LTE_FIGHTER")
  → sensor:    aesa, esm
    weapon:    MEDIUM_RANGE_RADAR_MISSILE, SHORT_RANGE_IR_MISSILE
    mover:     WSF_BRAWLER_MOVER
    processor: radar_track_cueing, weapon_datalink_manager
    include_path: platforms/lte_fighter.txt

afsim_types(kind="sensor", keyword="radar")   # 列传感器类型
afsim_types(name="aesa", kind="sensor")
  → base:       WSF_RADAR_SENSOR
    parameters: ignore_domain, initial_mode, selection_mode, slew_mode,
                azimuth_slew_limits, elevation_slew_limits, ...
    used_by:    AIR_MOVER_FIGHTER, DCA, ESCORT, LTE_FIGHTER
```

**默认只列含传感器或武器的平台类型是有意的**：一个既不能探测也不能开火的平台，
出现在交战想定里没有意义。每个组件类型还记录了它**接受哪些参数**和**被哪些平台
使用**，所以写组件时不用猜关键字。目录首次构建约 9 秒，之后走缓存。

**脚本处理器的接口**：这是"加了战术处理器却不开火"这个最常见故障的根因。目录会
把处理器声明的 `script_variables` 抽出来，标出**默认为空因而必须赋值**的变量，并
给出 demo 里的可用配置：

```
afsim_types(name="AA_TACTICS", kind="processor")
  script_interface:
    must_set = ['SENSOR_NAME', 'WEAPON_NAME']
  working_configuration:
    platform_type = BLUE_NAVAL_SAM_BATTERY
    on_initialize = [{WEAPON_NAME: "blue_naval_sam"}, {MAX_ENGAGEMENTS: "20"}]
```

赋值必须写在 `on_initialize` 块里；在 `script_variables` 里重声明会被 mission
拒绝——子 Agent 实测正是在这里卡住过。535 个组件类型中有 75 个带这样的脚本接口。

### 第 3 步：校验

`run_mission` 真正跑 mission.exe 并解析它的真实输出，而不是只看退出码：

```jsonc
{
  "ok": false,
  "returncode": 0,            // mission 自己认为成功
  "simulation_complete": true,
  "inert_simulation": true,   // 但只有 PLATFORM_INITIALIZED，什么都没发生
  "evt_events": 4,
  "evt_categories": { "PLATFORM_INITIALIZED": 4 },
  "problems": ["simulation ran but produced no activity: ..."]
}
```

判定失败的条件：Mission 报错、退出码非 0、超时、没跑到 `Simulation complete`、
**一个输出文件都没写**（`no_evidence`），或者**跑完了却只有 `PLATFORM_INITIALIZED`
事件**（`inert_simulation`）。

另有一类是"通过了但没法分析"（`not_analyzable`）：仿真确实跑了、`.aer` 也有内容，
但一条 `.evt` 事件都没记录——通常是想定里 `event_output` 的 `enable` 全被注释掉了。
这种情况返回 `ok: true` 并附 `caveat` 说明，而不是误判成失败。

报错带精确定位：

```
ERROR Unknown command: bogus_keyword
     at C:\proj\s.txt:2:22
     source: "bogus_keyword 5"
```

**关于内置库类**：`WSF_AIR_MOVER`、`WSF_RADAR_SENSOR` 这类是编译进 AFSIM 的，
demos 里不会声明，但 mission 认。目录把这类名字也收进来了（从别的类型的 `base`
字段和平台组件引用中反推），查不到时会明确区分"不在 demos 里"和"不是已知类型"，
不会像之前那样误导你说 `WSF_AIR_MOVER` 不存在。

**include 解析**：demo 里的类型文件用相对路径 include 兄弟文件，只有当入口的
`file_path` 也指向那个 demo 时才能解析。`run_mission` 遇到
`Cannot open file: X` 时会直接在诊断里给出可执行的修复行：

```jsonc
"include_resolution": {
  "found": true, "match": "basename",
  "candidates": [{
    "path": "air_to_air/platforms/lte_fighter.txt",
    "add_to_entry_file": "file_path C:\SoftCode\Sim\AFSim\demos\air_to_air"
  }]
}
```

**调试行为**：`include_stdout=true` 会带回 Mission 的原始 stdout。AFSIM 把
`show_state_transitions`、`show_task_messages` 这类行为诊断放在 stdout，
查"为什么这个战术处理器不开火"基本只能靠它。

### 第 5 步：分析

`analyze_run` 除了 KPI 和交战统计，还会给出 `diagnostics`，说明报告为什么是空的
——这两种情况完全不同：

```jsonc
"diagnostics": [
  { "issue": "empty_evt", "detail": "output/scn.evt is 0 bytes.",
    "likely_cause": "The scenario's event_output block enables no events..." },
  { "issue": "no_events", ... }
]
```

对比之下，一次健康的交战跑出来的 `diagnostics` 是 `[]`——**有诊断信息本身就是
信号**：它在告诉你结果可信还是不可信。

分析还给出 `first_event_sec` / `last_event_sec`（从全部解析记录算，不是从截断的
时间线），以及 `kill_attribution` 说明：AFSIM 的事件输出不记录击毁方的射手，
所以 `first_kill` 是按"损失方归给对面"推断的，油耗耗尽、坠毁或同归于尽都会被
算到对方头上——要下结论前请对照 `weapon_statistics`。

### 损失是怎么算出来的

`red_blue_losses` 里最容易被误读的是 `platforms_lost`。一发打出去的导弹在 AFSIM
里也是一个平台，命中后同样会产生 `PLATFORM_BROKEN`，所以"损失"这个词本身有歧义。
本项目不靠平台名字判断，判据全部取自事件流自身：

- `WEAPON_FIRED` 的第三个 token 就是这发弹的实例名，它随后会原样出现在
  `PLATFORM_BROKEN` 里。名字对上的记为 `weapons_expended`，不计入战斗损失。
- `PLATFORM_INITIALIZED` 列出想定开场就摆上场的平台。名字在其中的才算真实损失。
- 两者都覆盖不到时（`.evt` 被截断，或 `event_output` 没开这两类事件），该条
  损失进 `loss_accounting.unverified_losses`，照常计入 `platforms_lost`，但明确
  标注依据不足。

```jsonc
"loss_accounting": {
  "basis": "AFSIM event stream (WEAPON_FIRED / PLATFORM_INITIALIZED), not name spelling",
  "launched_weapon_platforms": 14,
  "initialized_platforms": 9,
  "unverified_loss_count": 0
}
```

早期版本用名字关键词判定，把 `BLUE_SAM_SITE` 因为含 "sam" 当成了一枚导弹，
于是一份零战斗损失的仿真报出 9 架飞机损失。宁可报"依据不足"，也不报一个看起来
精确、方向却错了的数字。

### 平台类型的域

`afsim_types` 的 `domain` 取自平台**自己声明的 mover**，并沿 `base` 链向上查找。
链上任何一环都没有声明 mover 的类型返回 `undetermined`——这是真实答案，不是失败。
早期版本会在类型名和定义文件路径里搜 "air""space" 这类词，结果把 GPS 归到
space、把 HVAA 和 SSM_MISSILE 归到 air。

## 仓库结构

```
core/knowledge/     AFSIM 知识库：只从安装目录提取事实
  source.py           归一化读取
  type_index.py       类型命名空间（platform_type / 组件类型 / 内置库类）
  mission_grammar.py  mission 输出的语法
core/policy.py      判断层：哪些事实算失败，具名可覆盖
core/runtime.py     执行器：进程
core/validation.py  执行器：跑 + 解析
core/analysis.py    执行器：evt → 指标
core/results.py     执行器：运行记录
core/server.py      配置解析与 JSON-RPC 分发
tools/              4 个工具的定义与路由
transport/stdio.py  stdio 传输入口
tests/
  test_layers.py     层级纪律：下层不得导入上层
  test_knowledge.py  知识层提取规则
  test_type_index.py 类型索引提取规则
  test_validation.py mission 输出解析
  test_protocol.py   MCP 协议
```

## 测试

```bash
python -m pytest tests/ -v
```

## 许可

MIT，见 `LICENSE`。

### 一个平台类型能不能开火

`platform_type` 继承是**叠加**的：派生类型只覆盖一个 mover，也会保留基类声明的
全部传感器、武器和处理器。所以只看类型自己那一段会把每个派生类型都读成裸的——
`SAM-MR_RB6` 会报"无传感器、无武器"，而它其实继承了 `SAM-MR` 的导引头和四个
处理器。`afsim_types` 因此同时给出两份：

- `components` —— 这个类型自己声明的
- `effective_components` —— 沿 `base` 链解析后的实际配置

还有一个坑：老版本里 `armed` 的定义是"声明了传感器**或**武器"，于是只有雷达、
根本没有导弹的阵地也被标成 armed。一个 Agent 挑中这样的类型建了防空阵地，工程
干净运行、返回 0、然后全场一弹未发，而 MCP 一直在说它是武装的。

现在分开报三个事实：

| 字段 | 含义 |
|---|---|
| `has_sensors` | 有效配置里有传感器 |
| `has_weapons` | 有效配置里有武器 |
| `has_processors` | 有效配置里有处理器 |
| `can_engage` | 同时有武器和处理器 |

`can_engage` 是必要条件而非充分条件：脚本处理器在变量没配之前仍然是惰性的，而
mission 不会在加载时拒绝一个没接线的平台——照样跑、照样返回 0、照样不开火。

### `<length-value>` 到底是什么

命令索引里每个带数值的参数都写成一个占位符——`altitude <length-value>`、
`end_time <time-value>`——而占位符正是语法变得不可校验的地方。`<length-value>`
是**两个 token**，第二个是单位，所以 `altitude 5000m msl` 会被拒，而索引无法
表达这个理由；`end_time 00:00:30` 也会被拒，因为 `<time-value>` 是一个数加一个
单位，不是时钟。这些全是一个 Agent 反复运行 mission 直到它不再报错试出来的。

AFSIM 在 `documentation/html/docs/argumenttypes.html` 里正式定义了这套产生式，
本项目直接读那份定义：

```
altitude <length-value>
  ->  altitude <real> <length-units>
      length-units 36 个可接受拼写: meters meter m kilometers km feet ft kft miles mi nm nmi cm mm ...
```

命令索引里 2267 个 `<*-value>` 占位符，现在 2068 个（91%）能被展开。剩下的是文档
本身没定义的（裸 `<value>`、`dbratio-value`、坐标类的 `X-value`），保持未定义。

拼写表里的每个词都来自 AFSIM 自己，不是谁试出来的。

### include 是怎么找文件的

`include` 找不到文件时的提示以前指向 demo 的顶层目录，于是给出
`file_path demos/suppressor`，而文件其实在 `demos/suppressor/platforms` 下面——
加了这行没有任何变化。

AFSIM 是把 `file_path` 条目拼到它被要求的名字上来找文件的，所以正确的条目不是文件
所在目录，而是**把请求的名字从文件路径里去掉之后剩下的目录**：

| mission 找不到 | 正确的 file_path |
|---|---|
| `sam_radar.txt` | `demos/suppressor/sensors/radar` |
| `sensors/radar/sam_radar.txt` | `demos/suppressor/platforms` |

搜索顺序取自 AFSIM File Commands 页的说明（它说这套算法和 C/C++ 预处理器一致）：
先做 `$(name)` / `${name}` 路径变量替换，然后绝对路径直接用，然后拼到**当前正在
处理的那个文件**所在目录，最后依次拼到每个 `file_path` 条目。`declared_duration`
也走同一套遍历，所以 `end_time` 写在被 include 的文件里一样算数——以前只读入口
文件，于是一份跑了 7200 秒的仿真一边报"用了 AFSIM 的 60 秒默认值"、一边建议加一个
已经存在且生效的 `end_time`。

### 仿真事件名

`event_output` 的 `enable` / `disable` 接受事件名，mission 对不认识的名字报
`Invalid event name for event_output`。这些名字既不在命令索引里（索引收的是命令，
不是命令的参数），也不可靠地在 HTML 文档里：`documentation/html/docs/event/`
有 80 页，而 AFSIM 自带 demo 里实际出现的 21 个事件有 17 个不在其中，包括
`PLATFORM_BROKEN` 和全部 `SENSOR_TRACK_*`、`LOCAL_TRACK_*`。

它们的声明在 SDK 头文件里。每个事件结果类给 `cNAME` 字符串一个字面量，那就是
`event_output` 接受的全集。这些类不集中在一个头文件里：核心的在
`WsfEventResults.hpp`，每个扩展自带一份——`WsfMilEventResults.hpp` 携带整个
`WEAPON_*` 事件族（`WEAPON_FIRED`、`WEAPON_HIT`、`WEAPON_MISSED`……）。
只读核心头文件会静默丢掉 55 个名字（早期版本就丢过整个武器事件族），所以索引
对 SDK include 树里所有 `*EventResults*.hpp` 取并集：**153 个**。GUI 工具的
偏好设置类也用 `cNAME`，但没有一个叫这个名字的文件，按文件名过滤即可精确排除。

```bash
afsim_command kind=event keyword=SENSOR_TRACK   # 列出
afsim_command name=PLATFORM_BROKEN              # 查一个
afsim_command name=WEAPON_FIRED                 # 武器事件族（扩展头文件声明）
afsim_command keyword=PLATFORM_BROKEN           # 查不到命令时自动回落到事件名
```

每个事件还带一个 `seen_in_demos` 标记，表示它是否真的在 AFSIM 自带场景的输出里
出现过——153 个里有 21 个。

### 实例接线：类型没写在那里的那一半

`afsim_types(name=...)` 返回的类型事实是"这个类型是什么"，但 BRAWLER_TEST 这类
战术类型族还有另一半事实藏在 demo 的入口想定里：**平台实例怎么接线**。指挥链
（`commander` / `command_chain`）、战术处理器读的 `script_variables`
（`MISSION_TYPE`、`ROUTE.Append`、`WINCHESTER`……）、`edit processor` 改配置——
这些都写在平台实例上，不写类型就不生效；入口文件自己还得带一个顶层
`script_variables` 全局块（`log`、`iout` 等），否则脚本上下文根本初始化不了。
省掉它们的表现完全静默：仿真照样跑、照样退出 0，只是跟踪了十分钟、一弹未发。

索引因此在构建时把 demo 入口里实例化每种类型的块解析出来（每型最多 3 份、按
完整度排序），连同入口文件的 include、命名航路和全局脚本变量一起返回。force
layout 常被入口委托给被 include 的 `scenarios/<名字>.txt`（往往经
`${SCNRIO}` 路径变量），而序言在父入口里——索引沿 include 链把父入口的
`$define`、序言逐行合并下来，并按"序言前 / 序言后"拆分父入口的 include：
消耗这些全局变量的 observer 必须在序言之后 include，放错位置脚本上下文就
初始化失败：

```
afsim_types(name="BLUE_FIGHTER")
  → demo_instantiations:
      file: air_to_air/scenarios/2v2.txt
      wiring:   commander SELF, command_chain IFLITE SELF, ...
                script_variables: START_TYPE = "route"; MISSION_TYPE = "SWEEP"; ...
      entry:    includes [platforms/lte_fighter.txt, observer.txt, ...]
                global_script_variables [closest_hostile, log_print, iout, ...]
```

照抄一份就是"这个类型被使用的方式"。配套地，`analyze_run` 把"跟踪很多、零开火"
单列为一个诊断项（`tracking_without_engagement`），并把原因指向实例接线而不是
让报告看起来只是运气不好。

### 脚本 API

战术处理器就是脚本，而脚本是写在对象上的——`PLATFORM`、`SENSOR`、`WEAPON`、
`TRACK`、`PROCESSOR`——以及它们的那些方法。这些此前在这个 server 上无处可查：
命令索引收的是输入文件命令，事件索引收的是事件名，所以"WsfTrack 有哪些方法"
在哪儿都没有答案。把一个处理器接起来，只能猜标识符，然后反复运行 mission 直到
它不再说 `Unknown identifier`。

产品自己文档化了：`documentation/html/docs/script/` 330 页，295 页是 WSF 类，
每页列出方法、返回类型、参数和说明；另外 208 个模型页在文档根目录也带脚本方法。
本项目把两处一起读，得到 **329 个类、4551 个方法**：

```bash
afsim_command kind=script name=WsfTrack        # 列出方法
afsim_command kind=script name=TrackQuality    # 按方法名反查是哪些类的
afsim_command kind=script keyword="track quality"  # 搜参数和说明正文
afsim_command kind=script                       # 列全部类
```

`WsfAssetManager` 的方法里有一组是 `GetEWRequired` / `GetTARRequired` /
`GetTTRRequired` / `GetWeaponRequired`——这就是"传感器没指定分类，资产永远不合格，
于是永远不开火"那条规则的接口面。现在它可查了。

`WsfTrack.TrackQuality()` 会连文档说明一起返回：*"Return the track's quality as
a value in the range [0..1]"*。

### 一个处理器要配成什么样才会开火

处理器出厂时 `SENSOR_NAME` / `WEAPON_NAME` 是空的，而 mission 拒绝在
`script_variables` 里重声明它们——只能在处理器内部的 `on_initialize` 块里赋值。

以前只返回第一条匹配，结果目录里 18 个需要外部配置的处理器，只有 1 个有示例，
其余 17 个被告知"要从脚本源码推断"——而答案就在旁边一行的派生类型里：

```
processor SR_SAM_TELAR_TASK_MGR TELAR_TASK_MGR
   on_initialize
      ACQ_SENSOR_NAME = "sr_sam_acq_radar_sensor";
      SENSOR_NAME     = "sr_sam_ttr_radar_sensor";
      WEAPON_NAME     = "sam";
      ...
```

现在按完整度排序返回**全部**示例，优先给出类型自己定义里那段（哪怕它在一个派生
类上），并逐条标明覆盖了哪些变量、还缺哪些。`TELAR_TASK_MGR`、`AA_TACTICS`、
`SAM_BATTERY_TASK_MGR` 都能直接拿到一份完整可抄的配置。

`on_initialize` 的存储也从"扁平赋值列表"改成"保留块边界"——实际使用时是整块照抄，
而需要 `SENSOR_NAME` 和 `WEAPON_NAME` 的处理器只有两者在**同一个块**里才工作。

### 交战包线

`zone` 是平台声明自己能在哪里活动、交战的地方，而 zone 的名字正是战术处理器里
`ENVELOPE = "..."` 要填的把手。两者必须一起给：只给范围不知道叫什么，只给名字
不知道边界。

```jsonc
"zones": [
  { "name": "full_kinematic", "shape": "circular",
    "extent": { "maximum_radius": "6 nm", "maximum_altitude": "20000 ft" } }
]
```

`SR_SAM_TELAR` 此前两个数字都看不见——`maximum_radius` 根本不在关键词表里，而且
`_performance` 只对组件调用、平台类型从来没调用过。一个 Agent 想知道这个阵地够
不着 9 km 高 60 km 外的目标，只能靠二分二十几个几何。现在一眼可见。

zones 和性能限值都沿 `base` 链继承，因为交战包线通常写在基类里。657 个平台类型
里 10 个声明了 zone，314 个带性能限值。

### 同一个关键字在不同块里参数不同

命令索引里 5646 条命令带着 `context` 字段，但埋得太深。`hits_to_establish_track`
要两个整数，而且只在传感器的 mode 块里合法——只读语法的人写
`hits_to_establish_track 3` 被拒，然后断定命令写错了，而不是自己放错了块。

现在每条 form 都带 `legal_in`（`_` 解释成 "top level"）和一句说明。`end_time` 就有
四种形式，其中三种限定在别的块内。
