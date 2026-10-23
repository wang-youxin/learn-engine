#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
learn-engine 雷达图生成器
从 profile.json + 主题路径状态计算能力轴分，输出带目标线的雷达图 HTML。

用法：
  python radar.py --profile <profile.json> --topic <主题目录> --out <输出html>
  python radar.py --demo          # 自带演示数据，看效果

依赖：仅标准库。无第三方包。
"""
import json
import math
import os
import sys
from datetime import datetime


# ---------- 几何 ----------

def poly_points(values, cx, cy, r, n):
    """values: 0-100 长度 n 的列表 → SVG 多边形点串"""
    pts = []
    for i, v in enumerate(values):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        rad = r * (max(0.0, min(100.0, v)) / 100.0)
        pts.append(f"{cx + rad * math.cos(ang):.1f},{cy + rad * math.sin(ang):.1f}")
    return " ".join(pts)


def axis_label_points(cx, cy, r, n):
    """返回每个轴标签的 (x, y, anchor)"""
    out = []
    for i in range(n):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        x = cx + (r + 26) * math.cos(ang)
        y = cy + (r + 26) * math.sin(ang)
        if x > cx + 6:
            anchor = "start"
        elif x < cx - 6:
            anchor = "end"
        else:
            anchor = "middle"
        out.append((x, y, anchor))
    return out


# ---------- 算分 ----------

def _upstream_ok(kps):
    """本轴所有 KP 的上游前置是否都已达标。
    达标 = 前置 KP 的 bloom_now >= 其 target_bloom。
    全部达标 → True（说明不是前置没学，是这层自己没学进去）。"""
    kp_map = {k["id"]: k for k in ALL_KPS}
    for k in kps:
        for dep in k.get("deps", []):
            d = kp_map.get(dep)
            if d is None:
                continue
            if d.get("bloom_now", 0) < d.get("target_bloom", 4):
                return False
    return True


def compute_axis(axis, kps):
    """
    axis: {"id":"A1","name":"概念辨析"}
    kps: 该轴下所有 KP 列表，每项含 bloom_now / target_bloom / deps
    cov   = 已测 KP 数 / 总数
    depth = Σbloom_now / (5 × 总数)
    score = 100 × (0.3×cov + 0.7×depth)
    target= 100 × (0.3×1.0 + 0.7×平均target_bloom/5)
    hub   = 依赖图中有多少个「其他轴的 KP」依赖本轴的 KP
    """
    total = len(kps)
    if total == 0:
        return {"id": axis["id"], "name": axis["name"], "score": 0.0,
                "target": 0.0, "gap": 0.0, "cov": 0.0, "depth": 0.0,
                "hub": 0, "measured": 0, "total": 0, "verdict": "无KP"}

    measured = [k for k in kps if k.get("bloom_now", 0) > 0]
    cov = len(measured) / total
    depth = sum(k.get("bloom_now", 0) for k in kps) / (5.0 * total)
    score = 100 * (0.3 * cov + 0.7 * depth)

    tgt_list = [k.get("target_bloom", 4) for k in kps]
    target = 100 * (0.3 * 1.0 + 0.7 * (sum(tgt_list) / len(tgt_list)) / 5.0)

    gap = target - score

    # 枢纽度：有多少个「别的 KP」依赖本轴的任一 KP
    own_ids = {k["id"] for k in kps}
    hub = sum(1 for other in ALL_KPS
              if other["id"] not in own_ids
              and own_ids & set(other.get("deps", [])))

    verdict = judge(gap, hub, _upstream_ok(kps))
    return {"id": axis["id"], "name": axis["name"], "score": round(score, 1),
            "target": round(target, 1), "gap": round(gap, 1),
            "cov": round(cov, 3), "depth": round(depth, 3),
            "hub": hub, "measured": len(measured), "total": total,
            "verdict": verdict}


def judge(gap, hub, upstream_ok):
    """相对目标的优劣判定。

    只用两个可机械计算的因子：gap（离目标多远）与 hub（是否卡住别人）。
    「是否支撑目标动作」这一层脚本判不了（需要 S0 映射表），
    因此 hub==0 的高缺口轴只给「独立短板（待判定）」，
    交 AI 依据 S0 动作映射表裁决，不在此处擅自判为「可忽略」。
    """
    if gap <= 15:
        if hub >= 2:
            return "真优势"
        if hub == 1:
            return "达标·单点支撑"
        return "达标但非枢纽"
    if gap >= 40 and upstream_ok:
        return "认知断层"
    if gap >= 30:
        return "关键短板" if hub >= 1 else "独立短板（待判定）"
    return "接近目标"


ALL_KPS = []


# ---------- HTML ----------

TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>能力雷达图 · {topic} · {date}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background:#FFFFFF; color:#2C2C2A; margin:0; padding:28px; }}
  h1 {{ font-size:16px; font-weight:500; margin:0 0 4px; }}
  .meta {{ font-size:12px; color:#5F5E5A; margin-bottom:20px; }}
  .wrap {{ display:flex; gap:28px; align-items:flex-start; flex-wrap:wrap; }}
  table {{ border-collapse:collapse; font-size:12px; }}
  th, td {{ border-bottom:1px solid rgba(0,0,0,.15); padding:7px 12px; text-align:left; }}
  th {{ font-weight:500; color:#5F5E5A; }}
  .v {{ font-weight:500; }}
  .v-真优势 {{ color:#0F6E56; }} .v-达标·单点支撑 {{ color:#0F6E56; }}
  .v-达标但非枢纽 {{ color:#888780; }}
  .v-关键短板 {{ color:#A32D2D; }} .v-独立短板（待判定） {{ color:#854F0B; }}
  .v-认知断层 {{ color:#854F0B; }} .v-接近目标 {{ color:#185FA5; }}
  .note {{ font-size:12px; color:#5F5E5A; margin-top:20px; line-height:1.6; max-width:640px; }}
  .legend {{ font-size:12px; margin-top:12px; }}
  .legend span {{ display:inline-block; margin-right:18px; }}
</style>
</head>
<body>
<h1>能力雷达图 · {topic}</h1>
<div class="meta">生成时间 {date} ｜ 目标动作 {n_goal} 条 ｜ 轴 {n_axis} 根</div>
<div class="wrap">
  <div>
  <svg width="440" height="400" viewBox="0 0 440 400" role="img" aria-label="能力雷达图">
    <circle cx="220" cy="200" r="140" fill="none" stroke="#D3D1C7" stroke-width="0.5"/>
    <circle cx="220" cy="200" r="98" fill="none" stroke="#D3D1C7" stroke-width="0.5"/>
    <circle cx="220" cy="200" r="56" fill="none" stroke="#D3D1C7" stroke-width="0.5"/>
    {grid_lines}
    <polygon points="{target_pts}" fill="none" stroke="#BA7517" stroke-width="1" stroke-dasharray="4 3"/>
    <polygon points="{cur_pts}" fill="#E6F1FB" fill-opacity="0.75" stroke="#185FA5" stroke-width="1.5"/>
    {dots}
    {labels}
  </svg>
  <div class="legend">
    <span><svg width="14" height="8"><rect width="14" height="3" y="2" fill="#185FA5"/></svg> 当前水平</span>
    <span><svg width="14" height="8"><line x1="0" y1="2" x2="14" y2="2" stroke="#BA7517" stroke-width="1" stroke-dasharray="3 2"/></svg> 目标线</span>
  </div>
  </div>
  <div>
  <table>
    <tr><th>轴</th><th>当前</th><th>目标</th><th>缺口</th><th>覆盖</th><th>枢纽</th><th>判定</th></tr>
    {rows}
  </table>
  </div>
</div>
<div class="note">{note}</div>
</body>
</html>
"""


def build_html(topic, axes_data, kps, goal_actions, note=""):
    n = len(axes_data)
    if n < 3:
        raise SystemExit("雷达图至少需要 3 根轴，当前只有 %d 根" % n)

    cx, cy, r = 220, 200, 140
    cur = [a["score"] for a in axes_data]
    tgt = [a["target"] for a in axes_data]

    grid = []
    for i in range(n):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        x = cx + r * math.cos(ang)
        y = cy + r * math.sin(ang)
        grid.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="#D3D1C7" stroke-width="0.5"/>')
    grid_lines = "\n    ".join(grid)

    dots = []
    for i, a in enumerate(axes_data):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        rad = r * (a["score"] / 100.0)
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#185FA5"/>')
    dots_s = "\n    ".join(dots)

    labels = []
    for (x, y, anchor), a in zip(axis_label_points(cx, cy, r, n), axes_data):
        labels.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="12" fill="#2C2C2A" '
                      f'text-anchor="{anchor}" dominant-baseline="central">{a["name"]}</text>')
        labels.append(f'<text x="{x:.1f}" y="{y + 14:.1f}" font-size="11" fill="#5F5E5A" '
                      f'text-anchor="{anchor}" dominant-baseline="central">{a["score"]:.0f}/{a["target"]:.0f}</text>')
    labels_s = "\n    ".join(labels)

    rows = []
    for a in axes_data:
        rows.append(
            f'<tr><td>{a["name"]}</td><td>{a["score"]:.0f}</td><td>{a["target"]:.0f}</td>'
            f'<td>{a["gap"]:.0f}</td><td>{a["measured"]}/{a["total"]}</td><td>{a["hub"]}</td>'
            f'<td class="v v-{a["verdict"]}">{a["verdict"]}</td></tr>')
    rows_s = "\n    ".join(rows)

    if not note:
        note = ("缺口 = 目标 − 当前。判定相对目标而非相对他人：真优势=接近目标且是枢纽；"
                "达标但非枢纽=到了目标但不解锁别人（不是杠杆）；关键短板=缺口大且卡住别人；"
                "独立短板（待判定）=缺口大但不卡别人，是否重要须对照 S0 目标动作映射表裁决；"
                "认知断层=缺口极大但上游已达标（学歪了，要重讲不是重练）。")

    return TPL.format(topic=topic, date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                      n_goal=len(goal_actions), n_axis=n,
                      grid_lines=grid_lines,
                      target_pts=poly_points(tgt, cx, cy, r, n),
                      cur_pts=poly_points(cur, cx, cy, r, n),
                      dots=dots_s, labels=labels_s, rows=rows_s, note=note)


# ---------- 载入 ----------

def load(topic_dir):
    """从主题目录读 路径.md/料库.md 里的 KP 状态，或从 profile.json 读"""
    global ALL_KPS
    profile_path = os.path.join(topic_dir, "..", "profile.json")
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    kps = []
    state_file = os.path.join(topic_dir, "状态.json")
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            kps = json.load(f).get("kps", [])
    ALL_KPS = kps

    axis_ids = json.load(open(os.path.join(topic_dir, "立项.json"), encoding="utf-8"))["axes"] \
        if os.path.exists(os.path.join(topic_dir, "立项.json")) else []
    pool = profile["axis_pool"]
    axes = [a for a in pool if a["id"] in axis_ids] or pool

    goal_file = os.path.join(topic_dir, "立项.json")
    goals = json.load(open(goal_file, encoding="utf-8")).get("goals", []) \
        if os.path.exists(goal_file) else []

    topic = json.load(open(goal_file, encoding="utf-8")).get("topic", "未命名主题") \
        if os.path.exists(goal_file) else "未命名主题"

    data = []
    for a in axes:
        axis_kps = [k for k in kps if k.get("axis") == a["id"]]
        if axis_kps:
            data.append(compute_axis(a, axis_kps))
    return topic, data, kps, goals


def demo():
    profile = {
        "axis_pool": [
            {"id": "A1", "name": "概念辨析"},
            {"id": "A2", "name": "结构化表达"},
            {"id": "A3", "name": "边界与风险"},
            {"id": "A4", "name": "工程直觉"},
            {"id": "A5", "name": "判断取舍"},
            {"id": "A6", "name": "度量设计"},
        ]
    }
    kps = [
        {"id": "KP1", "axis": "A1", "bloom_now": 5, "target_bloom": 4, "deps": []},
        {"id": "KP2", "axis": "A1", "bloom_now": 4, "target_bloom": 4, "deps": []},
        {"id": "KP3", "axis": "A1", "bloom_now": 3, "target_bloom": 4, "deps": []},
        {"id": "KP4", "axis": "A2", "bloom_now": 5, "target_bloom": 5, "deps": ["KP1"]},
        {"id": "KP5", "axis": "A2", "bloom_now": 4, "target_bloom": 5, "deps": ["KP4"]},
        {"id": "KP6", "axis": "A2", "bloom_now": 5, "target_bloom": 5, "deps": ["KP4"]},
        {"id": "KP7", "axis": "A3", "bloom_now": 2, "target_bloom": 4, "deps": []},
        {"id": "KP8", "axis": "A4", "bloom_now": 4, "target_bloom": 4, "deps": []},
        {"id": "KP9", "axis": "A5", "bloom_now": 3, "target_bloom": 4, "deps": ["KP7"]},
        {"id": "KP10", "axis": "A6", "bloom_now": 1, "target_bloom": 5, "deps": ["KP7"]},
        {"id": "KP11", "axis": "A6", "bloom_now": 2, "target_bloom": 5, "deps": ["KP10"]},
    ]
    global ALL_KPS
    ALL_KPS = kps
    axes = profile["axis_pool"]
    data = [compute_axis(a, [k for k in kps if k["axis"] == a["id"]]) for a in axes]
    goals = [{"id": "G1", "text": "写一份 AI 产品 PRD"}, {"id": "G2", "text": "做 AI 介入深度归类"}]
    html = build_html("演示主题（AI 产品经理）", data, kps, goals)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "雷达图-演示.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成：%s" % out)
    for d in data:
        print("  %-10s 当前 %5.1f / 目标 %5.1f  gap %6.1f  hub %d  → %s"
              % (d["name"], d["score"], d["target"], d["gap"], d["hub"], d["verdict"]))


def main():
    args = sys.argv[1:]
    if "--demo" in args:
        demo()
        return
    if "--profile" not in args or "--topic" not in args:
        print(__doc__)
        print("用法: python radar.py --profile <profile.json> --topic <主题目录> --out <输出html>")
        return
    p = args[args.index("--profile") + 1]
    t = args[args.index("--topic") + 1]
    out = args[args.index("--out") + 1] if "--out" in args else os.path.join(t, "报告", "雷达图.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    topic, data, kps, goals = load(t)
    if not data:
        raise SystemExit("没有可用的轴分数据，检查 状态.json 与 立项.json")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(topic, data, kps, goals))
    print("已生成：%s" % out)


if __name__ == "__main__":
    main()
