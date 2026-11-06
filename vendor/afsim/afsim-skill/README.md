# AFSIM-SKILL | v1.0.2

> [English](README_en.md) | 中文

> **第一次用？只需要 3 步，3 分钟搞定。**

支持 Cursor / Trae / VSCode + Continue / Claude Desktop 等所有实现了 MCP 协议的 IDE。

---

## 第一次使用（3 步）

### 第一步：打开本目录

在 Cursor 或 Trae 中打开 `AFSIM-SKILL/` 目录作为项目根目录。

IDE 会自动识别：

- `.cursor/commands/` 下的命令入口（`/afsim` `/afsim-auto` `/afsim-learn` `/afsim-debug`） 注意trae需要调整为.trae文件夹
- `SKILL.md` — AI 行为规范

### 第二步：开始对话

在 IDE 的 AI 对话窗口中输入：

```
/afsim
```

即可看到命令列表和快速开始指引。

### 第三步：选择子命令


| 命令                 | 适用场景                      |
| ------------------ | ------------------------- |
| `/afsim-auto`      | 快速生成 AFSIM 场景代码（全自动）      |
| `/afsim-auto step` | 逐模块构建，适合新手学习和复杂场景         |
| `/afsim-learn`     | 将你自己的 MD/PDF 文档解析融入 skill |
| `/afsim-debug`     | 遇到报错时，粘贴报错信息获取修正方案        |


---

## 功能

- **AFSIM 代码生成**：基于模板和官方 Demo，准确低报错
- **命令式交互**：`/afsim-auto` 全自动 / 半自动 / `/afsim-learn` 文档解析 / `/afsim-debug` 报错处理
- **渐进披露**：默认只加载核心文件，按需读取详细文档，上下文占用极小
- **两层教训体系**：条件反射式报错索引 + 应激激活深度教训
- **模板库**：基础到高级，复制即用
- **可扩展**：GUI 插件参数配置、更多 Demo 分类、教训持续积累

---

## 经验教学体系

AFSIM-SKILL 支持用户手动添加经验教学，通过两层架构实现渐进式防错：

### 两层架构


| 层级  | 文件                   | 说明                  |
| --- | -------------------- | ------------------- |
| 索引  | `refs/errors-ref.md` | 常见错误快速索引（条件反射）      |
| 教训  | `memory/cold/`       | 深度教训，应激激活（命中索引后才加载） |


### 教训库

核心文件：

- `memory/cold/lesson-root-causes.md` — 教训本体（按 3 大根因分类）
- `memory/cold/lesson-index.md` — 教训索引（快速定位）

三大根因分类：


| 分类     | 说明                   |
| ------ | -------------------- |
| 块结构错误  | `end_`* 缺失、块嵌套错误等    |
| 参数格式错误 | 坐标格式、单位错误、时间格式错误等    |
| 语义理解错误 | 混淆了不同基类型的用法、版本兼容性问题等 |


### 教训积累

每次遇到新报错并修正后：

1. 将报错模式和修正方案追加到 `refs/errors-ref.md`
2. 如果该错误有深层根因，创建对应教训追加到 `memory/cold/`

---

## 黄金法则

> **不要凭空自造 AFSIM 语法，要基于验证过的模板和官方 Demo 输出！**

---

## 项目结构

```
AFSIM-SKILL/
├── SKILL.md                   # AI 行为规范（核心入口）
├── .cursor/
│   └── commands/             # 命令入口
│       ├── afsim.md         # /afsim 主命令
│       ├── afsim-auto.md    # /afsim-auto 全自动/半自动
│       ├── afsim-learn.md   # /afsim-learn 文档解析
│       └── afsim-debug.md   # /afsim-debug 报错处理
├── refs/                      # 参考文档
│   ├── quick-ref.md         # 快速参考（黄金法则 + 最小原型）
│   ├── demos-index.md       # Demo 速查表
│   ├── errors-ref.md        # 报错索引
│   ├── complete-ref.md      # 完整语法参考
│   └── learn/              # /afsim-learn 解析的文档（本地，不上传）
├── output/                    # 成果管理
│   ├── staging/            # 临时成果（生成后初始位置）
│   └── verified/           # 成熟成果（用户认可后归档）
│       ├── scenario/       # 完整场景
│       ├── component/       # 可复用组件
│       └── template/        # 模板片段
├── memory/                    # 记忆体系
│   ├── hot/                # 当前会话教训
│   ├── cold/               # 长期教训库
│   │   ├── lesson-root-causes.md
│   │   └── lesson-index.md
│   └── user/               # 用户贡献区
├── templates/               # 代码模板
├── scripts/
│   ├── install.py          # 安装向导
│   └── parse_doc.py        # 文档解析脚本
├── user-data/              # 用户数据隔离（.gitignore）
└── .gitignore              # Git 忽略配置
```

---

## 常见问题

**提示 "Skill 未识别"**
请确认已在 Cursor/Trae 中打开了 `AFSIM-SKILL/` 目录作为项目根目录。

**报错处理不起作用？**
确认使用的是 `/afsim-debug` 命令，并将完整的报错信息粘贴进去（包括 Warlock/Wizard 的错误提示文本）。

---

## 关于

AFSIM-SKILL 由**海空兵棋**整理开发，参考了 AFSIM 官方文档和大量实战案例。

**海空兵棋**专注于 Command 系列和 AFSIM 等现代兵棋推演工具的 AI 辅助开发，提供：

- CMO-HKBQSKILL（Command Lua 代码生成）
- AFSIM-SKILL（AFSIM 场景代码生成）
- 实战兵棋教程与案例分享

欢迎关注海空兵棋与AI公众号，加入【兵推圈】**知识星球**交流学习。

---

## 许可证

本项目采用 [MIT License](LICENSE.md) 开源，欢迎商用。

---

## 更新日志

### 2026-05-26 | v1.0.2

- 新增 `[E019]` weapon 写在 platform 实例中的报错教训
- 新增 `[E020]` 输出文件相对路径的报错教训（相对 AFSIM 启动目录）
- 新增 `[L014]` weapon 声明位置教训
- 新增 `[L015]` 输出文件路径教训
- 完善两层教训体系

### 2026-05-25（第二次更新）

- 新增**成果管理闭环**：`output/` 目录，临时→验证→成熟三级管理
- 新增 `output/staging/` 临时成果区
- 新增 `output/verified/` 成熟成果区（scenario / component / template 三类）
- 代码生成输出改为文件写入，不再直接输出代码块
- 更新 afsim-auto、afsim-learn、afsim-debug 命令文件

### 2026-05-25

- 初始版本发布
- 支持 `/afsim-auto` 全自动 / 半自动代码生成
- 支持 `/afsim-learn` 文档解析融入
- 支持 `/afsim-debug` 报错处理 + 两层教训体系
- 渐进披露策略，最小化上下文占用

---

---


*Licensed under MIT · [海空兵棋](http://www.nawgsoft.com)*