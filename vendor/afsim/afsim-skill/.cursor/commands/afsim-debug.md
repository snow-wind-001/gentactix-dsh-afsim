# /afsim-debug — 报错处理与教训激活

> 粘贴 Warlock/Wizard 的报错信息，获取修正方案和相关教训。

## 使用方式

```
/afsim-debug
[粘贴报错信息]
```

## 核心原则

> **报错后绝不立即猜测根因。必须用断点（逐段注释/最小测试文件）隔离问题。**

---

## 处理流程

### Step 1: errors-ref 快速匹配

在 `refs/errors-ref.md` 中搜索报错关键字：
- `Unknown command`
- `Invalid position`
- `not found`
- `expected`
- `undefined`
- `syntax error`
- 具体命令名（如 `platform_type`、`radar_signature` 等）

匹配到 `[Exxx]` 条目后，记录相关教训 ID。

### Step 2: 教训激活（应激触发）

**仅在 errors-ref 命中时**，加载 `memory/cold/lesson-index.md` 查找相关教训 ID。

找到教训 ID 后，加载 `memory/cold/lesson-root-causes.md` 中对应段落。

### Step 3: 修正方案输出 + 断点验证

输出格式：

```
## 报错分析

[描述报错原因]

## 修正方案

```text
[修正后的代码片段]
```

## 断点测试计划

修正后，写一个最小化测试文件（只保留报错相关的最小片段），
验证修正是否正确。测试通过后再改主文件。

## Demo 参考

详见：`refs/demos-index.md` → [相关 Demo 名称]
```

### Step 4: 追加记录（需用户确认）

如果该报错在 errors-ref 中无记录：
1. 将报错模式和修正方案追加到 `refs/errors-ref.md`
2. 如果该错误有深层根因，创建对应教训追加到 `memory/cold/`

> **注意**：追加前必须等用户 Warlock 验证通过后再追加，不可提前追加未经确认的教训。

---

## 断点调试工作流（核心）

> 当报错信息不足以直接定位根因时，必须使用断点调试。

### 何时使用

- 报错关键字模糊（如 `Unknown weapon`、`not found`）
- 修正后错误依然存在
- 无法从报错行号直接推断问题

### 断点调试流程

1. **提取最小片段**：从原文件中提取报错相关的最小代码块
2. **写测试文件**：将最小片段写成独立测试文件（`output/staging/test_xxx.txt`）
3. **Warlock 验证**：用 Warlock 打开测试文件，确认是否仍报错
4. **逐步加回**：测试通过后，逐步加回被注释掉的代码，再次验证
5. **确认根因**：通过断点测试精确定位问题，然后修正原文件

### 断点测试文件命名规范

```
output/staging/test_<功能>_<编号>.txt
例如：
  test_weapon_type_1.txt   # 断点1：weapon 类型定义
  test_weapon_with_type_1.txt  # 断点2：weapon + platform_type
  test_<具体修正点>.txt
```

### 断点调试示例

```
场景：报错 "Unknown weapon: my_weapon"

断点1（最小化）：
  weapon MY_WEAPON WSF_EXPLICIT_WEAPON
     launched_platform_type MY_MISSILE
  end_weapon
  random_seed 1
  end_time 1 sec
  → Warlock 测试

断点2（加上 platform_type）：
  weapon MY_WEAPON WSF_EXPLICIT_WEAPON
     launched_platform_type MY_MISSILE
  end_weapon
  platform_type MY_MISSILE WSF_PLATFORM
  end_platform_type
  random_seed 1
  end_time 1 sec
  → Warlock 测试

断点3（加上 platform 实例）：
  weapon MY_WEAPON WSF_EXPLICIT_WEAPON
     launched_platform_type MY_MISSILE
  end_weapon
  platform_type MY_MISSILE WSF_PLATFORM
  end_platform_type
  platform test WSF_PLATFORM
     weapon my_weapon MY_WEAPON
     end_weapon
  end_platform
  random_seed 1
  end_time 1 sec
  → Warlock 测试

通过后，再加回其他配置（mover、sensor 等）
```

---

## 常见报错关键字速查

| 关键字 | 可能原因 |
|--------|----------|
| `Unknown command: platform_type` | 基类型缺失，应为 `platform_type NAME WSF_PLATFORM` |
| `Unknown command: radar_signature` | 基类型缺失，应为 `radar_signature NAME WSF_RADAR_SIGNATURE` |
| `Unknown weapon: <name>` | weapon 类型未定义 / 拼写不一致 / 定义顺序问题 |
| `Invalid position format` | 坐标格式错误，应为 `d:m:s N/S e/w` |
| `Mover not closed` | 缺少 `end_mover` |
| `Sensor not found` | 传感器名称未定义或拼写错误 |
| `expected` | 参数缺失或格式错误 |
| `not found` | 引用的名称不存在 |
