# /afsim-learn — 文档解析融入 Skill

> 将 MD/PDF 文档中的 AFSIM 语法要点解析并融入 skill。

## 使用方式

### 方式一：提供文件路径

```
/afsim-learn f:\docs\afsim_传感器教程.md
```

### 方式二：直接粘贴文档内容

```
/afsim-learn
[粘贴文档内容]
```

### 方式三：指定分类

```
/afsim-learn f:\docs\afsim_传感器教程.md sensor
```

支持的分类：sensor / weapon / platform / mover / processor / script / radar / comm / other

---

## 解析流程

### Step 1: 内容获取

读取文档内容（MD 直接读取，PDF 调用解析脚本）。

### Step 2: 语法提取

自动识别并提取：
- `platform_type` 定义块
- `sensor` / `weapon` / `mover` / `processor` 配置块
- 坐标格式（`d:m:s N/S e/w`）
- 参数格式（时间、速度、单位）
- 注释和说明
- 关键概念和术语

### Step 3: 分类存入

解析结果存入 `refs/learn/` 对应分类目录：

```
refs/learn/
├── sensor.md
├── weapon.md
├── platform.md
├── mover.md
├── processor.md
├── script.md
├── radar.md
├── comm.md
└── other.md
```

每个文件按「来源文档」分隔，格式：

```markdown
---
source: afsim_传感器教程.md
date: 2026-05-25
---

## platform_type SENSOR_EXAMPLE (来源: xxx.md)

### 关键语法

sensor find WSF_GEOMETRIC_SENSOR
   location 0 0 0 m
   ignore_same_side
   frame_time 10 sec
   reports_location
   on
   track_quality 0.5
end_sensor

**注意**：`sensor` 后必须跟传感器名称（如 `find`），然后才是基类型（如 `WSF_GEOMETRIC_SENSOR`）。不能省略名称。

### 注意事项

- location 指定传感器在平台上的位置
- frame_time 影响传感器刷新率
```

### Step 4: 对比验证（关键步骤）

**必须**与 `refs/complete-ref.md` 交叉对比：

1. 对每个提取出的语法参数，在 `complete-ref.md` 中查找是否有相同参数
2. 若发现 skill 文档中**未记录的新参数**，标记为「待验证 ⚠️」
3. 若发现参数值与 skill 记录不一致，标记为「疑似冲突 ⚠️」

```
验证结果格式：
- [✅] 参数名 X：与 complete-ref.md 一致
- [⚠️] 参数名 Y：未在 complete-ref.md 中记录（待验证）
- [⚠️] 参数名 Z：值与 skill 记录不符（疑似新语法）
```

### Step 5: 冲突检测

对于每个提取的语法块：
1. 若同名块（如 `sensor find`）已在 `refs/learn/` 中存在，对比参数列表
2. 参数完全相同 → 跳过（避免重复）
3. 参数有差异 → 追加为「疑似新语法变体 ⚠️」，**不覆盖**原记录
4. 新块类型 → 直接追加

### Step 6: 更新索引

解析完成后：
1. 在 `refs/demos-index.md` 中补充来源文档信息
2. 若发现新错误模式，同步追加到 `refs/errors-ref.md`
3. 若发现新深层教训，同步追加到 `memory/cold/`

---

## 解析脚本

对于 PDF 文件，使用 `scripts/parse_doc.py`：

```bash
python scripts/parse_doc.py f:\docs\afsim.pdf --category sensor
```

支持的格式：`.md`（直接读取）、`.pdf`（调用 parse_doc.py）

---

## 融入规则

- 提取的代码片段**必须保持原始格式**，不得修改语法
- 每个来源文档在目标文件中用 `---` 分隔，包含 source 和 date 元信息
- 如果某个语法模式已有记录，追加到现有条目后，不要覆盖
- 如果提取到新的错误模式或教训，同步追加到 `refs/errors-ref.md`
- **新参数必须对比 `refs/complete-ref.md`**：已记录的标记为 ✅，未记录的标记为 ⚠️ 待验证
- **冲突不覆盖**：同一块类型的不同参数值追加为「疑似新语法变体 ⚠️」
