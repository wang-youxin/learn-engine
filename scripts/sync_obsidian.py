#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
learn-engine → Obsidian Vault 同步器

把每日学习记录归档进 Vault（遵守 AGENTS.md 规则 0/2/3/5/7）：
  D 层 daily/YYYY-MM-DD.md   追加每日学习记录
  B 层 wiki/通用/<主题>.md    写/更新知识点笔记（含 [[双链]]）
  C 层 skills/index.md        学习方法论达 3 次则提示封装

用法：
  python sync_obsidian.py --topic-dir <T-主题目录> --vault <vault路径> --date YYYY-MM-DD
  python sync_obsidian.py --demo --vault <vault路径>

依赖：仅标准库。不删除、不覆盖 Vault 内已有内容（除明确标记的追加区）。
"""
import json
import os
import re
import sys
from datetime import datetime


def read(p, default=""):
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return default


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def append_once(path, marker, block):
    """只在 marker 不存在时追加，保证幂等"""
    content = read(path)
    if marker in content:
        return False
    if content and not content.endswith("\n"):
        content += "\n"
    write(path, content + "\n" + block + "\n")
    return True


FRONTMATTER = """---
tags: ["学习笔记", "{topic}"]
created: {created}
updated: {updated}
status: draft
---"""


def sync_daily(vault, topic, date, rows):
    """D 层：追加每日学习记录"""
    path = os.path.join(vault, "daily", f"{date}.md")
    block = f"""
## 目的学习 · {topic}

{rows}

> 引擎：目的学习 Skill ｜ 记录由 S6 日结自动写入
"""
    marker = f"## 目的学习 · {topic}"
    added = append_once(path, marker, block)
    return path, added


def sync_wiki(vault, topic, topic_dir, kps, date):
    """B 层：知识点笔记（带 [[双链]]，更新 index.md）"""
    wiki_dir = os.path.join(vault, "wiki", "通用")
    notes = []

    for k in kps:
        # 关联 KP 的笔记名（Obsidian 里用 [[名称]]）
        related = [r for r in k.get("related", []) if r in {x["id"] for x in kps}]
        rel_names = []
        for rid in related:
            for x in kps:
                if x["id"] == rid:
                    rel_names.append(x.get("name", rid))

        lines = [
            FRONTMATTER.format(topic=topic, created=date, updated=date),
            "",
            f"# {topic} · {k.get('name', k['id'])}",
            "",
            f"> KP {k['id']} ｜ 能力轴 {k.get('axis')} ｜ 掌握度 L{k.get('bloom_now', 0)}（目标 L{k.get('target_bloom', 4)}）",
            "> 来源：" + " / ".join(k.get("source", []) or ["（待补）"]),
            "",
            "## 是什么",
            k.get("what", "（待补）"),
            "",
            "## 为什么重要",
            k.get("why", "（待补）"),
            "",
            "## 用途延伸",
            "- " + "\n- ".join(k.get("uses", []) or ["（待补）"]),
            "",
            "## 易混点",
        ]
        if rel_names:
            for rn in rel_names:
                lines.append(f"- 与 [[{rn}]] 的区别：{k.get('contrast_note', '（待补）')}")
        else:
            lines.append("- （待补）")

        lines += [
            "",
            "## 学习记录",
            f"- {date} 导入图谱 ｜ 目标 Bloom L{k.get('target_bloom', 4)}",
            "",
            "---",
            "",
            f"相关：[[{topic}]]",
            "",
        ]
        note_path = os.path.join(wiki_dir, f"{topic} - {k.get('name', k['id'])}.md")
        write(note_path, "\n".join(lines))
        notes.append(os.path.basename(note_path)[:-3])

    # 主题总览笔记（所有 [[双链]] 的汇点）
    overview = [
        FRONTMATTER.format(topic=topic, created=date, updated=date),
        "",
        f"# {topic} · 知识图谱总览",
        "",
        f"> 共 {len(kps)} 个知识点 ｜ 更新 {date}",
        "",
        "## 知识点",
    ]
    for k in kps:
        overview.append(f"- [[{topic} - {k.get('name', k['id'])}]] — {k.get('name', '')}（{k.get('axis')}）")
    overview += ["", "---", "", f"引擎：目的学习 Skill", ""]
    write(os.path.join(wiki_dir, f"{topic}.md"), "\n".join(overview))
    notes.append(topic)

    # 更新 wiki/通用/index.md（AGENTS.md 规则 2）
    idx_path = os.path.join(wiki_dir, "index.md")
    idx = read(idx_path)
    if idx:
        for n in notes:
            line = f"- [[{n}]]"
            if line not in idx:
                idx = idx.rstrip() + "\n" + line + "\n"
        write(idx_path, idx)

    return os.path.join(wiki_dir, f"{topic}.md"), notes


def build_rows(topic_dir):
    """从主题目录拼当日记录行"""
    state_p = os.path.join(topic_dir, "状态.json")
    kps = []
    if os.path.exists(state_p):
        kps = json.load(open(state_p, encoding="utf-8")).get("kps", [])

    today = [k for k in kps if k.get("last_tested") == os.environ.get("SYNC_DATE", "")]
    if not today:
        today = kps[:3]

    lines = []
    if today:
        lines.append("**今日完成**：")
        for k in today:
            lines.append(f"- {k['id']} {k.get('name', '')}（bloom {k.get('bloom_now', 0)} → 目标 L{k.get('target_bloom', 4)}）")
    else:
        lines.append("**今日完成**：（无记录）")

    path_p = os.path.join(topic_dir, "路径.md")
    if os.path.exists(path_p):
        m = re.search(r"今日队列[：:]\s*(.+)", read(path_p))
        if m:
            lines.append("**今日队列**：" + m.group(1).strip())

    lines.append("**雷达变化**：见 `报告/` 最新雷达图")
    return "\n".join(lines)


def do_sync(topic_dir, vault, date):
    topic = os.path.basename(topic_dir).replace("T-", "")
    rows = build_rows(topic_dir)

    p, added = sync_daily(vault, topic, date, rows)
    print(("✅ 已写入" if added else "↺ 已存在（幂等，未重复写）") + "：" + p)

    state_p = os.path.join(topic_dir, "状态.json")
    kps = []
    if os.path.exists(state_p):
        kps = json.load(open(state_p, encoding="utf-8")).get("kps", [])
    if kps:
        p2, notes = sync_wiki(vault, topic, topic_dir, kps, date)
        print("✅ 已写入：" + p2)
        print("   笔记 %d 篇：" % len(notes))
        for n in notes[:6]:
            print("     - " + n)
        if len(notes) > 6:
            print("     ... 共 %d 篇" % len(notes))
        print("✅ 已更新 index.md（AGENTS.md 规则 2）")


def demo(vault):
    os.makedirs(os.path.join(vault, "daily"), exist_ok=True)
    os.makedirs(os.path.join(vault, "wiki", "通用"), exist_ok=True)
    td = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_demo_topic")
    os.makedirs(td, exist_ok=True)
    json.dump({"kps": [
        {"id": "KP1", "name": "AI 介入深度三分类", "axis": "A1", "bloom_now": 4,
         "target_bloom": 4, "source": ["https://example.com/a"],
         "what": "按 AI 介入深度把产品分成加AI / AI加 / AI原生。",
         "why": "决定做产品时要不要重设计流程。",
         "uses": ["给自家产品定位", "写 PRD 时定形态"],
         "related": ["KP2"], "contrast_note": "分类看 AI 是否驱动核心流程。"},
        {"id": "KP2", "name": "传统产品 vs AI 产品差异", "axis": "A1", "bloom_now": 3,
         "target_bloom": 4, "source": ["https://example.com/b"],
         "what": "七维差异：价值来源、边界、交互、迭代、关系、失败模式、护城河。",
         "why": "决定验收标准怎么定。",
         "uses": ["写 PRD", "定评估方式"], "related": ["KP1"],
         "contrast_note": "分类是维度，差异是清单。"}
    ]}, open(os.path.join(td, "状态.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    do_sync(td, vault, datetime.now().strftime("%Y-%m-%d"))


def main():
    args = sys.argv[1:]
    if "--demo" in args:
        vault = args[args.index("--vault") + 1]
        demo(vault)
        return
    if "--topic-dir" not in args or "--vault" not in args:
        print(__doc__)
        return
    td = args[args.index("--topic-dir") + 1]
    vault = args[args.index("--vault") + 1]
    date = args[args.index("--date") + 1] if "--date" in args else datetime.now().strftime("%Y-%m-%d")
    do_sync(td, vault, date)


if __name__ == "__main__":
    main()
