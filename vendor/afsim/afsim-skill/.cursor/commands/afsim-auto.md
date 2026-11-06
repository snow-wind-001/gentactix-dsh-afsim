# /afsim-auto — AFSIM 代码自动生成

## 两种模式

### 全自动（`/afsim-auto <需求>`）

接收需求 → 自动解析 → 找模板 → 生成 → 自检 → 输出。全流程无需确认。

### 半自动（`/afsim-auto step <需求>`）

每次只生成一个模块，每步等待确认后再继续。适合新手学习或复杂场景。

---

## 全自动模式流程

### Step 0: 需求理解

解析用户描述，提取关键要素：
- 平台类型（飞机/舰船/地面/导弹）
- 阵营（红方/蓝方/绿方）
- 是否带传感器、武器、处理器
- 仿真时长
- 特殊功能（行为树、路由、雷达等）

**需求模糊时**，全自动模式会尝试推断并补充默认值，必要时在输出后提示用户确认。

### Step 1: 加载模板

按需求类型加载对应模板：

| 需求类型 | 模板来源 |
|----------|----------|
| 飞机平台 | `refs/quick-ref.md` 最小原型 + `templates/` |
| 舰船/地面 | `refs/demos-index.md` 找 launcher/ship demo |
| 带传感器 | `refs/demos-index.md` 找 sensor demo |
| 带武器 | `refs/demos-index.md` 找 weapon/engage demo |
| 复杂逻辑 | `refs/demos-index.md` 找 processor/script demo |

### Step 2: 代码生成

基于模板修正输出，遵循：
- 不凭空自造语法
- 块结构完整（所有 `end_*` 存在）
- 基类型正确（`WSF_PLATFORM`、`WSF_AIR_MOVER` 等）
- 参数格式正确（坐标 d:m:s、时间单位、速度单位）

### Step 3: 自检

生成后自动检查：
- [ ] 所有 `end_*` 闭合完整
- [ ] 基类型拼写正确
- [ ] 参数格式正确
- [ ] 单位正确（ft、kts、m 等）
- [ ] 无行尾注释

### Step 4: 输出到 staging

将生成的代码**写入文件**到 `output/staging/`，**不直接输出代码块**：

```
文件路径：output/staging/<场景名称>.txt
文件内容：[生成的 AFSIM 代码]
```

同时告知用户：
- 输出路径
- 内容摘要（包含哪些 platform_type、sensor、weapon 等）
- 下一步操作（用 Warlock 打开验证）

### Step 5: 归档闭环

用户认可后（或 Warlock 验证通过），将文件移动到 `output/verified/` 对应子目录：

```
mv output/staging/<name>.txt output/verified/scenario/
mv output/staging/<name>.txt output/verified/component/
mv output/staging/<name>.txt output/verified/template/
```

在目标目录的 README 中追加元信息（来源、日期、功能描述）。

---

## 半自动模式流程（step）

### 逐模块构建清单

```
Task Progress:
- [ ] Step 1: 需求确认
- [ ] Step 2: 基础平台定义（platform_type + platform）
- [ ] Step 3: 传感器（如有）
- [ ] Step 4: 武器（如有）
- [ ] Step 5: 处理器/脚本逻辑（如有）
- [ ] Step 6: 路路由与阵位
- [ ] Step 7: 全局配置（random_seed, end_time, log_file）
- [ ] Step 8: 自检确认
```

### Step 1: 需求确认

解析用户需求，输出需求摘要，等待确认：
```
我将为你构建以下 AFSIM 场景：
- 红方 SAM 系统 vs 蓝方战机
- 包含：LAUNCHER_TYPE（platform_type）、FINDER_SENSOR、TIR_SENSOR、LRSAM_WEAPON、TRACK_PROCESSOR
- 仿真时长：50 min

确认请回复 "是" 或补充信息。
```

### Step 2-7: 逐模块生成

每个模块生成后等待确认：
```
【Step 2/8】基础平台定义

platform_type LAUNCHER_TYPE WSF_PLATFORM
   side red
   icon SA-10_Launcher
   weapon lrsam LRSAM
     quantity 1
   end_weapon
end_platform_type

platform launcher1 LAUNCHER_TYPE
   side red
   position 40:00:00n 116:00:00e altitude 0 ft msl
end_platform

确认以上平台定义？[是/修改/跳过]
```

### Step 8: 自检确认 + 写入 staging

所有模块确认后，将最终代码写入 `output/staging/<场景名称>.txt`，告知用户路径和内容摘要。

---

## 自检清单

- [ ] 所有 `end_*` 闭合完整
- [ ] 基类型正确（`WSF_PLATFORM` / `WSF_AIR_MOVER` / `WSF_SURFACE_MOVER` 等）
- [ ] 参数格式正确（坐标 `d:m:s N/S e/w`、时间 `30 sec`、速度 `300 kts` 等）
- [ ] 单位正确（altitude `ft msl` / `m agl`、RCS `m^2` 等）
- [ ] 无行尾注释（AFSIM 不支持行尾注释）
- [ ] 阵营名称一致
- [ ] 在 Warlock/Wizard 中加载验证

---

## 模板来源

- 最小原型：`refs/quick-ref.md`
- Demo 速查：`refs/demos-index.md`
- 完整语法：`refs/complete-ref.md`
- 成熟案例：`output/verified/`
- 官方模板：`templates/`
