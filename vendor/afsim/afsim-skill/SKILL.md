---
name: afsim-skill
description: AFSIM 场景代码生成、报错调试、文档解析。触发词：/afsim /afsim-auto /afsim-learn /afsim-debug。当前版本：v1.0.2。当用户提到 AFSIM、Warlock、platform_type、sensor、weapon、mover、route、AFSIM 场景/兵棋推演时使用本 Skill。
disable-model-invocation: true
version: v1.0.2
version_date: 2026-05-26
---

# AFSIM Skill — 核心入口 | v1.0.2

> 精简入口，详细工作流见 `.cursor/commands/` 下的各子命令文件。

## 黄金法则

> **不要凭空自造 AFSIM 语法，要基于验证过的模板和官方 Demo 输出！**
>
> AI 可基于模板修正/组合输出，但新手不建议自造。报错 → errors-ref 匹配 → 教训激活 → 积累。

## 渐进披露

本 Skill 采用渐进披露策略节省上下文：

| 层级 | 文件 | 何时加载 |
|------|------|----------|
| 0（始终） | 本文件 | 默认 |
| 1（按需） | `refs/errors-ref.md` | 报错时快速匹配 |
| 2（命中后） | `memory/cold/lesson-index.md` | errors-ref 命中特定条目时 |
| 3（匹配后） | `memory/cold/lesson-root-causes.md` | lesson-index 匹配到教训 ID 时 |
| 4（查询时） | `refs/quick-ref.md` | 需要模板时 |
| 5（查询时） | `refs/demos-index.md` | 需要 Demo 时 |
| 6（查询时） | `refs/complete-ref.md` | 需要完整语法参考时 |

## 教训体系：索引 + 激活联动

### Layer 1: errors-ref.md（快速索引，条件反射）

报错时**第一反应**去 `refs/errors-ref.md` 快速匹配。
格式：`## [E001] 报错关键字 → 根因 → 修正方案 → Demo路径`

### Layer 2: memory/cold/（深度教训，应激激活）

**不主动加载**，仅当 errors-ref 命中特定条目时触发：

1. errors-ref 命中 `[Exxx]` → 查 `memory/cold/lesson-index.md` 找相关教训 ID
2. 加载 `memory/cold/lesson-root-causes.md` 中对应教训段落
3. 输出修正方案 + 教训提醒

### 联动流程

```
用户报错 → refs/errors-ref.md 匹配 → 命中 [Exxx]
                                          ↓
                              lesson-index.md 查教训 ID
                                          ↓
                              lesson-root-causes.md 加载教训段落
                                          ↓
                              输出修正方案 + 教训提醒
```

## 代码生成原则

1. **基于模板输出**：不凭空自造，优先在 `refs/quick-ref.md` / `templates/` 找模板
2. **不明确则交互**：需求模糊时询问关键参数（平台类型、武器、传感器、仿真时长等）
3. **自检后输出**：检查块结构、基类型、参数格式、单位
4. **成果存入 output 目录**：不得直接输出，告知用户保存路径（见下方成果管理闭环）

## 成果管理闭环

所有生成的代码通过 **临时 → 验证 → 成熟** 三阶段闭环管理：

### 目录结构

```
output/
├── staging/           # 临时成果区（初始输出位置）
│   └── [生成的 .txt / .md 文件]
└── verified/         # 成熟成果区（用户认可后归档）
    ├── scenario/     # 完整场景（可运行的 .txt 场景文件）
    ├── component/   # 组件模块（platform_type、processor 等可复用块）
    └── template/    # 模板片段（可直接复制到新场景的参数组合）
```

### 生命周期

```
生成代码 → 存入 output/staging/ → Warlock 验证
    ↓
[用户认可] → 从 staging 移动到 verified/ 对应子目录
    ↓
[后续生成] → 从 verified/ 中选取成熟案例作为参考
```

### 归档触发

以下任一条件满足时，将 `output/staging/` 中的文件移动到 `output/verified/` 对应子目录：

1. **用户明确认可**："确认"、"很好"、"这个可以"
2. **通过 Warlock/Wizard 验证**：`Warlock successfully loaded` 无报错
3. **仿真运行成功**：end_time 内正常终止，无崩溃

### 归档操作

```text
# 用户认可后，AI 执行归档
mv output/staging/xxx.txt output/verified/scenario/

# 同时在 verified/scenario/README.md 记录元信息
```

### 参考成熟成果

生成新代码时，优先从 `output/verified/` 中找同类案例作为参考（仅次于 `templates/` 和官方 Demo）。

## 命令入口

| 命令 | 功能 |
|------|------|
| `/afsim` | 显示命令列表和快速参考 |
| `/afsim-auto` | 全自动代码生成 |
| `/afsim-auto step` | 半自动，逐模块确认 |
| `/afsim-learn` | 解析 MD/PDF 文档，融入 skill |
| `/afsim-debug` | 报错处理，联动教训体系 |

## 参考

- 快速参考：`refs/quick-ref.md`
- Demo 速查：`refs/demos-index.md`
- 报错索引：`refs/errors-ref.md`
- 完整语法：`refs/complete-ref.md`
- 教训索引：`memory/cold/lesson-index.md`
- 教训本体：`memory/cold/lesson-root-causes.md`
- 模板目录：`templates/`
- 成果目录：`output/staging/`（临时）/ `output/verified/`（成熟）

---

## 已验证语法白名单

> 以下语法已通过官方 Demo 交叉验证，生成代码时应优先使用。⚠️ 标记的参数需进一步确认。

### sensor 高级参数

|| 块类型 | 参数 | 验证来源 | 备注 |
|--------|--------|------|--------|------|
| sensor | `receive_only` | sensor_demos.md ~42 | 纯接收模式 |
| sensor | `transmit_only` | sensor_demos.md ~68 | 纯发射模式 |
| sensor | `maximum_range` | sensor_demos.md ~3085 | 快速剔除范围 |
| sensor | `minimum_range` | sensor_demos.md ~2083 | 最小探测距离 |
| sensor | `frame_time` | engage.md ~54 | 刷新频率 |
| sensor | `scan_mode` | sensor_demos.md ~1387 | azimuth / azimuth_and_elevation |
| sensor | `azimuth_scan_limits` | sensor_demos.md ~1388 | 方位扫描范围 |
| sensor | `antenna_height` | sensor_demos.md ~1384 | 用于地形遮蔽 |
| sensor | `antenna_tilt` | sensor_demos.md ~1385 | 波束下倾角 |
| sensor | `location` | engage.md ~2912 | NED 坐标系位置 |
| sensor | `internal_link` | engage.md ~58 | 连接处理器 |
| sensor | `integration_gain` | sensor_demos.md ~57 | 信号处理增益 |
| sensor | `probability_of_false_alarm` | sensor_demos.md ~1840 | 虚警概率 |
| sensor | `required_pd` | sensor_demos.md ~1841 | 所需发现概率 |
| sensor | `one_m2_detect_range` | sensor_demos.md ~2086 | 1m² RCS 的探测距离 |
| sensor | `hits_to_establish_track` | sensor_demos.md ~2658 | 建立航迹所需命中数 |
| sensor | `reports_range` | sensor_demos.md ~62 | 报告距离 |
| sensor | `reports_bearing` | sensor_demos.md ~63 | 报告方位 |
| sensor | `reports_location` | engage.md ~55 | 报告位置 |
| sensor | `ignore_same_side` | engage.md ~53 | 忽略同阵营 |

### antenna_pattern 方向图类型

|| 类型关键词 | 验证来源 | 备注 |
|-----------|---------|------|
| `constant` | sensor_demos.md ~31 | 常数增益 |
| `circular_pattern` | sensor_demos.md ~1371 | 圆锥波束 |
| `rectangular_pattern` | sensor_demos.md ~1495 | 矩形波束 |
| `constant_pattern` | sensor_demos.md ~342 | 恒定方向图 |
| `sine_pattern` | sensor_demos.md ~3067 | 正弦方向图 |
| `uniform_pattern` | sensor_demos.md ~2617 | 均匀全向 |

### processor 状态机

|| 参数 | 验证来源 | 备注 |
|------|------|---------|------|
| `show_state_transitions` | engage.md ~71 | 调试输出 |
| `evaluation_interval` | engage.md ~73 | 多状态独立配置 |
| `next_state` | engage.md ~75 | 状态转换目标 |

### comm 通信

|| 参数 | 验证来源 | 备注 |
|------|---------|------|
| `internal_link` | engage.md ~27 | 内部链路 |
| `frequency` | sensor_demos.md ~49 | 工作频率 |
| `maximum_range` | comm.md ~110 | 通信距离 |
| `power` | sensor_demos.md ~75 | 发射功率 |

### space_mover 轨道

|| 参数 | 验证来源 | 备注 |
|------|---------|------|
| `semi_major_axis` | satellite_demos.md ~834 | 半长轴 km |
| `eccentricity` | satellite_demos.md ~832 | 离心率 |
| `inclination` | satellite_demos.md ~833 | 轨道倾角 |
| `raan` | satellite_demos.md ~216 | 升交点赤经 |
| `anomaly` | satellite_demos.md ~217 | 近地点幅角 |
| `revs_per_day` | satellite_demos.md ~5611 | 每日转数 |

### 全局配置

|| 参数 | 验证来源 | 备注 |
|------|---------|------|
| `start_date` | satellite_demos.md ~1042 | 仿真开始日期 |
| `start_time` | satellite_demos.md ~1043 | 仿真开始时间 |
| `end_time` | engage.md ~59 | 结束时间 |
| `random_seed` | quick-ref.md | 随机种子 |
| `thread_count` | engage.md ~13 | 并行线程数 |
| `realtime` | script_demos.md ~61 | 实时仿真 |
| `event_output` | script_demos.md ~327 | 事件输出 |
| `event_pipe` | script_demos.md ~121 | 事件管道 |
| `dis_interface` | script_demos.md ~62 | DIS 接口 |
| `include` | engage.md ~15 | 包含外部文件 |
| `include_once` | base_types.md ~315 | 仅包含一次 |
| `define_path_variable` | satellite_demos.md ~184 | 路径变量 |
| `file_path` | satellite_demos.md ~187 | 文件搜索路径 |

### 签名定义

|| 类型 | 有无基类型 | 验证来源 | 备注 |
|------|------|----------|---------|------|
| `radar_signature` | 有（WSF_RADAR_SIGNATURE） | engage.md ~18 | 常用 |
| `optical_signature` | 两种皆可 | base_types.md ~17 | Demo 中多无基类型 |
| `constant` | - | base_types.md ~18 | 固定值 |
| `plt_file` | - | base_types.md ~46978 | 频率依赖 RCS |
| `bistatic_signature` | - | base_types.md ~47069 | 双基地雷达 |
