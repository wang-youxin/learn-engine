#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
learn-engine 知识图谱工具：校验 + 杠杆排序 + Pareto 核心 20%

用法：
  python graph.py validate --graph <graph.json>          # 校验图谱（S2 闸门）
  python graph.py rank    --graph <graph.json>            # 杠杆排序 + 核心 20%
  python graph.py topo    --graph <graph.json>            # 拓扑分层（前置关系）
  python graph.py demo                                    # 自带演示

依赖：仅标准库。
"""
import json
import os
import sys
from collections import defaultdict, deque


def load_graph(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def kp_map(g):
    return {k["id"]: k for k in g["kps"]}


# ---------- 校验（S2 闸门） ----------

def validate(g):
    """返回 (通过?, 问题列表)"""
    problems = []
    km = kp_map(g)

    if not g["kps"]:
        return False, ["图谱为空：没有拆出任何知识点"]

    # 1. KP 数量
    n = len(g["kps"])
    if n < 12 or n > 20:
        problems.append(f"⚠ KP 数量 {n}，建议 12-20 个（<12 主题太窄，>20 应切子主题）")

    # 2. 每 KP 必备字段
    for k in g["kps"]:
        kid = k.get("id", "?")
        if not k.get("name"):
            problems.append(f"❌ {kid} 缺 name")
        if k.get("axis") not in g.get("axes", []):
            problems.append(f"❌ {kid} 的 axis='{k.get('axis')}' 不在 axes 列表 {g.get('axes')}")
        if not k.get("target_bloom"):
            problems.append(f"❌ {kid} 缺 target_bloom")
        if not k.get("source"):
            problems.append(f"❌ {kid} 没有来源链接 → 不许进图谱")

        # 3. 至少 1 条边
        edges = len(k.get("deps", [])) + len(k.get("related", [])) + len(k.get("contrast", []))
        if edges == 0:
            problems.append(f"❌ {kid} 是孤岛（无任何 deps/related/contrast 边）→ 图谱没建好")

        # 4. 边指向的 KP 必须存在
        for e in (k.get("deps", []) + k.get("related", []) + k.get("contrast", [])):
            if e not in km:
                problems.append(f"❌ {kid} 的边指向不存在的 KP：{e}")

    # 5. 依赖图必须无环
    cyc = find_cycle(g)
    if cyc:
        problems.append(f"❌ 依赖图有环：{' → '.join(cyc)}（deps 必须是无环图）")

    # 6. 对比边必须成对（contrast 是对称关系）
    for k in g["kps"]:
        for c in k.get("contrast", []):
            if c in km and k["id"] not in km[c].get("contrast", []):
                problems.append(f"⚠ 对比边不对称：{k['id']} ↔ {c}，只标了一边")

    # 7. value / freq 必须在 0-1
    for k in g["kps"]:
        for fld in ("value", "freq"):
            v = k.get(fld)
            if v is None:
                problems.append(f"❌ {kid_name(k)} 缺 {fld}（无法算杠杆）")
            elif not (0 <= v <= 1):
                problems.append(f"❌ {kid_name(k)} 的 {fld}={v} 超出 0-1")

    hard = [p for p in problems if p.startswith("❌")]
    return (len(hard) == 0), problems


def kid_name(k):
    return k.get("id", "?") + " " + (k.get("name", "")[:12])


def find_cycle(g):
    """DFS 找依赖环，返回环路径或 None"""
    km = kp_map(g)
    WHITE, GREY, BLACK = 0, 1, 2
    color = defaultdict(int)
    stack = []

    def dfs(u):
        color[u] = GREY
        stack.append(u)
        for v in km.get(u, {}).get("deps", []):
            if v not in km:
                continue
            if color[v] == GREY:
                idx = stack.index(v)
                return stack[idx:] + [v]
            if color[v] == WHITE:
                r = dfs(v)
                if r:
                    return r
        stack.pop()
        color[u] = BLACK
        return None

    for k in g["kps"]:
        if color[k["id"]] == WHITE:
            r = dfs(k["id"])
            if r:
                return r
    return None


# ---------- 杠杆计算 ----------

def compute_leverage(g):
    km = kp_map(g)
    # 入度：多少个其他 KP 依赖它
    indeg = defaultdict(int)
    for k in g["kps"]:
        for d in k.get("deps", []):
            if d in km:
                indeg[d] += 1
    max_hub = max(indeg.values()) if indeg else 1
    max_hub = max(max_hub, 1)

    out = {}
    for k in g["kps"]:
        hub_n = indeg.get(k["id"], 0) / max_hub
        value = k.get("value", 0.0)
        freq = k.get("freq", 0.0)
        lev = 0.5 * hub_n + 0.3 * value + 0.2 * freq
        out[k["id"]] = {
            "id": k["id"], "name": k.get("name", ""), "axis": k.get("axis"),
            "hub": indeg.get(k["id"], 0), "hub_norm": round(hub_n, 3),
            "value": value, "freq": freq,
            "leverage": round(lev, 4),
            "target_bloom": k.get("target_bloom", 4),
            "bloom_now": k.get("bloom_now", 0),
            "deps": k.get("deps", []),
        }
    return out


def pareto_core(lev):
    """最重要 20% ∪ 最常用 20%"""
    items = list(lev.values())
    n = len(items)
    k = max(1, int(n * 0.2 + 0.999))  # 向上取整

    by_value = sorted(items, key=lambda x: -x["value"])[:k]
    by_freq = sorted(items, key=lambda x: -x["freq"])[:k]
    core = {}
    for x in by_value:
        core[x["id"]] = "最重要20%"
    for x in by_freq:
        core.setdefault(x["id"], "")
        core[x["id"]] = (core[x["id"]] + "+最常用20%").strip("+")
    return core


def rank(g):
    lev = compute_leverage(g)
    core = pareto_core(lev)
    for kid, why in core.items():
        lev[kid]["core"] = why
    for x in lev.values():
        x.setdefault("core", "")

    # 拓扑约束：deps 未达标的后继不得在前
    ready = [x for x in lev.values()
             if all((lev.get(d, {}).get("bloom_now", 0) >= lev.get(d, {}).get("target_bloom", 4) - 1)
                    for d in x["deps"])]
    ready.sort(key=lambda x: (-(1 if x.get("core") else 0), -x["leverage"]))

    return lev, core, ready


# ---------- 拓扑分层 ----------

def topo_layers(g):
    """返回按层分组的 KP：第 0 层无未达标前置，可立即学"""
    km = kp_map(g)
    indeg = {k["id"]: 0 for k in g["kps"]}
    adj = defaultdict(list)
    for k in g["kps"]:
        for d in k.get("deps", []):
            if d in km:
                indeg[k["id"]] += 1
                adj[d].append(k["id"])

    q = deque(sorted([i for i, d in indeg.items() if d == 0]))
    layers = []
    cur = list(q)
    seen = set()
    while cur:
        layers.append(sorted(cur))
        nxt = []
        for u in cur:
            seen.add(u)
            for v in adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    nxt.append(v)
        cur = sorted(nxt)
    missing = [i for i in indeg if i not in seen]
    if missing:
        layers.append(sorted(missing))
    return layers


# ---------- 输出 ----------

def do_validate(path):
    g = load_graph(path)
    ok, problems = validate(g)
    print("图谱校验：%s" % ("✅ 通过" if ok else "❌ 不通过"))
    if problems:
        for p in problems:
            print("  " + p)
    if ok:
        print("  无硬伤。可以进 S3 分段诊断。")
    return 0 if ok else 1


def do_rank(path):
    g = load_graph(path)
    ok, problems = validate(g)
    hard = [p for p in problems if p.startswith("❌")]
    if hard:
        print("❌ 图谱校验不通过，排序中止。先修这些硬伤：\n")
        for p in hard:
            print("  " + p)
        print("\n（软提醒：%s）" % ("；".join(p for p in problems if p.startswith("⚠")) or "无"))
        return 1
    if problems:
        print("⚠ 校验通过，但有软提醒：")
        for p in problems:
            print("  " + p)
        print()

    lev, core, ready = rank(g)
    print("=== 杠杆排序（全图）===")
    for x in sorted(lev.values(), key=lambda y: -y["leverage"]):
        tag = ("【核心:%s】" % x["core"]) if x.get("core") else ""
        print("  %-6s %-30s lev=%.3f (hub=%d val=%.2f freq=%.2f) %s"
              % (x["id"], x["name"][:28], x["leverage"], x["hub"], x["value"], x["freq"], tag))
    print()
    print("=== 今日可学队列（拓扑允许 + 杠杆降序）===")
    if not ready:
        print("  （空：全部 KP 的前置都未达标 → 先解前置）")
    for i, x in enumerate(ready, 1):
        tag = ("★核心" if x.get("core") else "")
        print("  %d. %-6s %-30s %s" % (i, x["id"], x["name"][:28], tag))
    return 0


def do_topo(path):
    g = load_graph(path)
    layers = topo_layers(g)
    print("=== 拓扑分层（前置关系）===")
    for i, layer in enumerate(layers):
        print("  第 %d 层：%s" % (i, "、".join(layer)))
    return 0


def demo():
    g = {
        "topic": "demo",
        "axes": ["A1", "A2", "A3", "A6"],
        "kps": [
            {"id": "KP1", "name": "AI 介入深度三分类", "axis": "A1", "target_bloom": 4,
             "deps": [], "related": ["KP2"], "contrast": ["KP2"], "value": 0.9, "freq": 0.9,
             "source": ["https://a"], "bloom_now": 4},
            {"id": "KP2", "name": "传统产品 vs AI 产品差异", "axis": "A1", "target_bloom": 4,
             "deps": [], "related": ["KP1"], "contrast": ["KP1"], "value": 0.6, "freq": 0.7,
             "source": ["https://b"], "bloom_now": 3},
            {"id": "KP3", "name": "评估三集（基线/回归/边界）", "axis": "A6", "target_bloom": 5,
             "deps": ["KP1"], "related": ["KP4"], "contrast": [], "value": 0.95, "freq": 0.8,
             "source": ["https://c"], "bloom_now": 1},
            {"id": "KP4", "name": "数据闭环与数据飞轮", "axis": "A6", "target_bloom": 4,
             "deps": ["KP3"], "related": ["KP3"], "contrast": [], "value": 0.7, "freq": 0.5,
             "source": ["https://d"], "bloom_now": 0},
            {"id": "KP5", "name": "灰度发布与分阶段上线", "axis": "A6", "target_bloom": 4,
             "deps": [], "related": [], "contrast": [], "value": 0.4, "freq": 0.6,
             "source": ["https://e"], "bloom_now": 0},
        ],
    }
    ok, problems = validate(g)
    print("=== 校验 ===")
    print("  %s" % ("✅ 通过" if ok else "❌ 不通过"))
    for p in problems:
        print("  " + p)
    print()
    lev, core, ready = rank(g)
    print("=== 杠杆排序 ===")
    for x in sorted(lev.values(), key=lambda y: -y["leverage"]):
        tag = ("【核心:%s】" % x["core"]) if x.get("core") else ""
        print("  %-6s %-28s lev=%.3f (hub=%d val=%.2f freq=%.2f) %s"
              % (x["id"], x["name"][:26], x["leverage"], x["hub"], x["value"], x["freq"], tag))
    print()
    print("=== 今日可学队列 ===")
    for i, x in enumerate(ready, 1):
        tag = ("★核心" if x.get("core") else "")
        print("  %d. %-6s %-28s %s" % (i, x["id"], x["name"][:26], tag))
    print()
    print("=== 拓扑分层 ===")
    for i, layer in enumerate(topo_layers(g)):
        print("  第 %d 层：%s" % (i, "、".join(layer)))


def main():
    args = sys.argv[1:]
    if not args or args[0] == "demo":
        demo()
        return
    cmd = args[0]
    if "--graph" not in args:
        print(__doc__)
        return
    path = args[args.index("--graph") + 1]
    if cmd == "validate":
        sys.exit(do_validate(path))
    elif cmd == "rank":
        sys.exit(do_rank(path))
    elif cmd == "topo":
        sys.exit(do_topo(path))
    else:
        print("未知命令：%s" % cmd)
        print(__doc__)


if __name__ == "__main__":
    main()
