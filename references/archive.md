# 档案 schema 与迁移协议

## 目录结构

```
学习引擎/学习档案/
├── profile.json                    # 全局档案（所有主题共用）
└── T-<主题slug>/
    ├── 立项.json                    # 机器可读：目标动作 + 轴选择 + 依赖映射
    ├── 立项.md                      # 人读版
    ├── 料库.md                      # KP + 来源 + 冲突标记 + 依赖
    ├── 状态.json                    # 机器可读：每个 KP 的 bloom_now / 状态
    ├── 路径.md                      # 排序结果 + 每日队列
    ├── 诊断.md                      # S3 前置题与结果
    ├── 补充/                        # S7 生成物
    └── 报告/
        ├── YYYYMMDD.md
        └── YYYYMMDD-雷达图.html
```

## profile.json

```json
{
  "schema": "v1",
  "updated_at": "2026-10-23",
  "axis_pool": [
    {
      "id": "A1",
      "name": "概念辨析",
      "criterion": "能说清两个近似概念的本质区别，而非背定义",
      "added_at": "2026-10-23"
    }
  ],
  "axis_scores": {
    "A1": {
      "score": 86.0,
      "target": 86.0,
      "measured_kps": 3,
      "total_kps": 3,
      "last_tested": "2026-10-23",
      "evidence": ["T-ai-pm:KP1", "T-ai-pm:KP2"]
    }
  },
  "weak_points": [
    {
      "id": "W-KP7",
      "text": "评估三集（基线/回归/边界）只记定义不会设计",
      "axis": "A6",
      "first_seen": "2026-10-23",
      "last_seen": "2026-10-23",
      "clear_streak": 0,
      "sources": ["T-ai-pm"]
    }
  ],
  "radar_history": [
    {
      "date": "2026-10-23",
      "topic": "T-ai-pm",
      "scores": { "A1": 86.0, "A2": 95.3 },
      "targets": { "A1": 86.0, "A2": 100.0 }
    }
  ]
}
```

### 字段约定

| 字段 | 规则 |
|------|------|
| `axis_scores` | 一个轴一个条目，全局唯一。跨主题汇总同一根轴。 |
| `weak_points` | **只增不减**。某弱点连续两次测试无弱点才移除（`clear_streak` 累计到 2）。 |
| `radar_history` | 只追加。每次日结 append 一条，永不覆盖。 |
| `evidence` | 每个分数必须能追到具体的 `主题:KP` 对。这是防"AI 编分数"的锚。 |

## 状态.json（每个主题一份）

```json
{
  "topic": "ai-pm",
  "updated_at": "2026-10-23",
  "kps": [
    {
      "id": "KP7",
      "name": "效果评估体系（基线/回归/边界）+ 数据闭环",
      "axis": "A6",
      "target_bloom": 5,
      "bloom_now": 2,
      "deps": ["KP1", "KP2"],
      "status": "learning",
      "source": ["https://..."],
      "conflict": false,
      "attempts": 1,
      "last_tested": "2026-10-23",
      "wrong_answer_ref": "logs/20261023.md#Q4"
    }
  ]
}
```

| 字段 | 规则 |
|------|------|
| `bloom_now` | L1=1 … L6=6，0=未测。**只升不降**，除非显式重测（重测要在 history 里留痕）。 |
| `status` | `untested` / `learning` / `passed` / `rework`（回炉） |
| `wrong_answer_ref` | 错答的存档位置。**S7 补充材料必须引用它**——没这个字段就生不成合格的补充。 |
| `deps` | 前置 KP ID 列表。S4 排程的硬约束依据。 |

## 幂等规则

| 场景 | 行为 |
|------|------|
| 重复跑同一主题 S6 | 不丢历史：更新 `axis_scores`，`radar_history` append 一条，`weak_points` 更新 `last_seen` 但不清零 |
| 重复跑 S3 诊断 | 覆盖该 KP 的 `bloom_now` 初值（诊断就是定初值），history 留痕 |
| 同一 KP 连续两次测都达标 | 该弱点 `clear_streak += 1`；达到 2 才从 `weak_points` 移除，且**移入 archive 不删除** |
| 主题文件夹重跑 | 不覆盖 `补充/` 已有文件，同名加日期后缀 |

## 从 「材料驱动型」学习 Skill 迁移

现有资产：`<课程工作区>/既有评估存档的 levels.json`（多课有数据）

### 迁移步骤

1. **建轴**：把 各课的 KP 按语义归入 A1-A6。归类时写下判据，**不要硬塞**——归不进任何轴的 KP 说明轴池缺一根，走扩轴规则。
2. **迁分数**：材料驱动型 Skill 的 `bloom_level`（每课一个 L 级）不能直接当轴分——它是一课的整体级，不是某个轴的级。正确做法是按 `kp_coverage` 里每个 KP 的达成级，逐 KP 填 `bloom_now`，再由脚本重算轴分。
3. **迁弱点**：`personal_weak_kps` 里的每一条 原样进 `weak_points`，`clear_streak = 0`，`sources` 填来源课次。
4. **建主题**：把 已有课程归为一个主题 `T-ai-course`（因为它们属于同一条主线），`立项.json` 的 goals 用 材料驱动型 Skill 已有的"学习目标"条目。

### 迁移后的 sanity check

```
python scripts/radar.py --profile 学习档案/profile.json --topic 学习档案/T-ai-course --out 临时检查.html
```
跑出来的轴分应与 材料驱动型 Skill 的整体结论方向一致：各课整体在同一 Bloom 级，说明大部分轴接近目标，唯一明显凹陷的应是 A6 度量设计（因为"评估体系"在 材料驱动型 Skill 里正是反复出现的薄弱点）。**如果结果不一致，是迁移归类错了，不是脚本错了。**

## 存档边界

- 档案只记**学习状态**，不记与学习无关的个人信息。
- 报告里的错答原文会留在 `wrong_answer_ref` 指向的日志里——这是 S7 生成补充材料的必要输入，属于学习数据，保留。
- 档案不出现在任何公开内容里。
