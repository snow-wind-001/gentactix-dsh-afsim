# /afsim — 主命令入口

> 显示 AFSIM-SKILL 命令列表和快速参考。

## 命令列表

| 命令 | 功能 |
|------|------|
| `/afsim-auto` | 全自动代码生成，无需确认直接输出 |
| `/afsim-auto step` | 半自动，逐模块确认，适合学习/复杂场景 |
| `/afsim-learn <文档路径或内容>` | 解析 MD/PDF 文档，融入 skill |
| `/afsim-debug` | 报错处理，粘贴 Warlock/Wizard 报错信息获取修正 |

## 黄金法则

> **不要凭空自造 AFSIM 语法，要基于验证过的模板和官方 Demo 输出！**

## 快速开始

### 新建场景（推荐用 `/afsim-auto step`）

```
/afsim-auto step
```

按提示输入需求，例如："做一个红方萨姆防空系统对抗蓝方战机的场景"

AI 会逐模块确认：platform_type → sensor → weapon → route → processor，每步等待你的确认。

### 快速生成（用 `/afsim-auto`）

```
/afsim-auto 做一个红方萨姆防空系统对抗蓝方战机的场景
```

AI 自动完成全流程，直接输出代码。

### 学习文档（用 `/afsim-learn`）

```
/afsim-learn 将这个.md文件解析进skill：f:\docs\afsim_传感器.md
```

AI 自动解析文档中的 AFSIM 语法要点，存入 `refs/learn/` 对应分类。

### 报错处理（用 `/afsim-debug`）

```
/afsim-debug
```

粘贴 Warlock/Wizard 的报错信息，AI 会匹配 errors-ref 并激活相关教训，给出修正方案。

## 快速参考

AFSIM 代码的核心块结构：

```text
radar_signature NAME
  constant 10 m^2
end_radar_signature

platform_type NAME WSF_PLATFORM
  side blue
  icon F-18E
  radar_signature NAME
  mover WSF_AIR_MOVER
     debug
  end_mover
end_platform_type

platform instance_name TYPE
  side blue
  route
     position 30:00:00n 120:00:00e altitude 10000 ft msl
        speed 300 kts
  end_route
end_platform

random_seed 1
end_time 30 sec
```

> 完整模板见 `refs/quick-ref.md`
> Demo 速查见 `refs/demos-index.md`
