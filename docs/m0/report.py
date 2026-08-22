#!/usr/bin/env python3
"""M0 検証（仕様書 §4）の集計スクリプト。

attendance.csv と daily-log.csv を読んで、H-1 / H-3 の判定、日別参加率、
お題ランキング、継続曲線を出力する。毎日実行してよい（途中経過が見える）。

    python3 docs/m0/report.py
    python3 docs/m0/report.py --dir path/to/data
    python3 docs/m0/report.py --demo
"""

import argparse
import csv
import os
import random
import re
import sys
import unicodedata

H1_GOAL = 0.20          # 初日参加者のうち最終日も参加した割合
H3_GOAL = 1.5           # 日別参加率の 最大÷最小
YES = {"1", "o", "O", "○", "◯", "y", "Y", "yes", "true", "TRUE", "✓"}

DAY_COL = re.compile(r"^d(\d+)$")


def width(s):
    """全角を2文字幅として数える。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n, align="left"):
    s = str(s)
    gap = max(0, n - width(s))
    return s + " " * gap if align == "left" else " " * gap + s


def table(headers, rows, aligns=None):
    aligns = aligns or ["left"] * len(headers)
    widths = [max(width(str(h)), *(width(str(r[i])) for r in rows)) if rows
              else width(str(h)) for i, h in enumerate(headers)]
    out = ["  ".join(pad(h, widths[i], aligns[i]) for i, h in enumerate(headers)),
           "  ".join("-" * w for w in widths)]
    for r in rows:
        out.append("  ".join(pad(r[i], widths[i], aligns[i]) for i in range(len(headers))))
    return "\n".join(out)


def bar(value, maximum, size=20):
    if maximum <= 0:
        return ""
    return "█" * max(1, round(value / maximum * size)) if value else ""


def load_attendance(path):
    """[(participant_id, {day: bool|None})] を返す。None は未記入（未実施日）。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return [], []
    days = sorted(int(m.group(1)) for c in rows[0] if c and (m := DAY_COL.match(c.strip())))
    people = []
    for r in rows:
        pid = (r.get("participant_id") or "").strip()
        if not pid:
            continue
        marks = {}
        for d in days:
            raw = (r.get(f"d{d:02d}") or r.get(f"d{d}") or "").strip()
            marks[d] = None if raw == "" else (raw in YES)
        people.append((pid, marks))
    return people, days


def load_odai(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        out = {}
        for r in csv.DictReader(f):
            try:
                out[int((r.get("day") or "").strip())] = (r.get("odai") or "").strip()
            except ValueError:
                continue
        return out


def demo_data(n=60, days=14):
    """動作確認用の合成データ。想定通りの形（Day3/13 が山、Day10/11 が谷）で生成する。"""
    rnd = random.Random(20260822)
    appeal = {3: 1.35, 13: 1.30, 5: 1.15, 2: 1.05, 10: 0.70, 11: 0.65, 6: 0.85, 9: 0.85}
    people = []
    for i in range(n):
        marks, alive = {}, True
        for d in range(1, days + 1):
            base = 0.92 * (0.955 ** (d - 1)) * appeal.get(d, 1.0)
            if d > 1 and not alive and rnd.random() > 0.25:
                marks[d] = False
                continue
            hit = rnd.random() < min(0.98, base)
            marks[d] = hit
            alive = hit or rnd.random() < 0.5
        people.append((f"p{i+1:03d}", marks))
    return people, list(range(1, days + 1))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="M0 検証の集計")
    ap.add_argument("--dir", default=here, help="attendance.csv / daily-log.csv のあるディレクトリ")
    ap.add_argument("--demo", action="store_true", help="合成データで動作確認する")
    args = ap.parse_args()

    if args.demo:
        people, days = demo_data()
        odai = load_odai(os.path.join(here, "daily-log.csv"))
        print("※ --demo：合成データで実行しています。実際の検証結果ではありません。\n")
    else:
        path = os.path.join(args.dir, "attendance.csv")
        if not os.path.exists(path):
            sys.exit(f"見つかりません: {path}")
        people, days = load_attendance(path)
        odai = load_odai(os.path.join(args.dir, "daily-log.csv"))
        if not people:
            sys.exit("attendance.csv に参加者の行がありません。\n"
                     "参加者を1人1行で登録してから再実行してください（--demo で書式を確認できます）。")

    n = len(people)
    # 1人でも記入があれば「実施済みの日」とみなす
    done = [d for d in days if any(m[d] is not None for _, m in people)]
    if not done:
        sys.exit(f"登録者 {n}人。まだ1日も記録がありません（Day 1 の結果を入れてから実行してください）。")

    count = {d: sum(1 for _, m in people if m[d]) for d in done}
    rate = {d: count[d] / n for d in done}

    print("=" * 64)
    print("M0 検証レポート（仕様書 §4）")
    print("=" * 64)
    print(f"登録者 {n}人 / 実施 {len(done)}日（Day {done[0]}〜{done[-1]}）"
          f" / 延べ投稿 {sum(count.values())}件\n")

    # ---- 日別 ----
    rows, seen = [], set()
    prev = set()
    peak = max(count.values())
    for d in done:
        today = {p for p, m in people if m[d]}
        new = len(today - seen)
        back = len(today & seen - prev)
        gone = len(prev - today)
        rows.append([f"Day {d}", odai.get(d, "-"), count[d], f"{rate[d]*100:5.1f}%",
                     new, back, gone, bar(count[d], peak)])
        seen |= today
        prev = today
    print(table(["日", "お題", "参加", "参加率", "新規", "復帰", "離脱", ""], rows,
                ["left", "left", "right", "right", "right", "right", "right", "left"]))
    print()

    # ---- H-1 ----
    first, last = done[0], done[-1]
    cohort = {p for p, m in people if m[first]}
    stayed = {p for p in cohort if people_map(people)[p][last]}
    h1 = len(stayed) / len(cohort) if cohort else 0.0
    final = last == days[-1]
    print("-" * 64)
    print(f"H-1  初日({first}日目)の参加者 {len(cohort)}人 → Day {last} も参加 {len(stayed)}人")
    print(f"     {h1*100:.1f}%   基準 {H1_GOAL*100:.0f}%   "
          f"{verdict(h1 >= H1_GOAL)}{'' if final else '  ※ 途中経過'}")

    # ---- H-3 ----
    hi, lo = max(done, key=lambda d: rate[d]), min(done, key=lambda d: rate[d])
    h3 = rate[hi] / rate[lo] if rate[lo] else float("inf")
    print("-" * 64)
    print(f"H-3  最高 Day {hi}「{odai.get(hi,'-')}」{rate[hi]*100:.1f}%  /  "
          f"最低 Day {lo}「{odai.get(lo,'-')}」{rate[lo]*100:.1f}%")
    print(f"     {h3:.2f}倍   基準 {H3_GOAL}倍   "
          f"{verdict(h3 >= H3_GOAL)}{'' if final else '  ※ 途中経過'}")
    print("-" * 64)
    print("H-2  ヒアリング（interview.md）で手動判定。10人中5人以上が")
    print("     こちらから聞く前に他人の投稿へ言及すれば Go")
    print("-" * 64)
    print()

    # ---- お題ランキング（K-5 の予行） ----
    print("お題ランキング（参加率順 / 仕様書 K-5）")
    rank = sorted(done, key=lambda d: -rate[d])
    print(table(["順", "日", "お題", "参加率"],
                [[i + 1, f"Day {d}", odai.get(d, "-"), f"{rate[d]*100:5.1f}%"]
                 for i, d in enumerate(rank)],
                ["right", "left", "left", "right"]))
    print()
    if len(rank) >= 6:
        worst = rank[-3:]
        print("下位3本は §7.2 の採用基準（30秒 / 場所非依存 / 正解が無い / 説明不要 / 安全）の")
        print("どれで落ちたかを必ず言語化する →  " +
              " , ".join(f"Day {d}「{odai.get(d,'-')}」" for d in worst))
        print()

    # ---- 継続曲線 ----
    print(f"継続曲線（Day {first} 参加者 {len(cohort)}人のその後）")
    curve = []
    for d in done:
        alive = sum(1 for p in cohort if people_map(people)[p][d])
        r = alive / len(cohort) if cohort else 0
        curve.append([f"Day {d}", alive, f"{r*100:5.1f}%", bar(alive, len(cohort))])
    print(table(["日", "残存", "残存率", ""], curve, ["left", "right", "right", "left"]))
    print()

    if not final:
        print(f"※ Day {days[-1]} まで記録すると最終判定になります（現在 Day {last} まで）。")


_MAP_CACHE = {}


def people_map(people):
    key = id(people)
    if key not in _MAP_CACHE:
        _MAP_CACHE[key] = dict(people)
    return _MAP_CACHE[key]


def verdict(ok):
    return "✅ Go" if ok else "❌ No-Go"


if __name__ == "__main__":
    main()
