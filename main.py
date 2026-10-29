#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ExamForge 智能组卷工作台 — 蓝图驱动的本地组卷引擎（纯标准库，零依赖）。

题库是一个 JSON 文件；蓝图规定题型配额、分值、难度分布与知识点覆盖；
引擎用「贪心配平 + 交换改进」选题，同一题库 + 蓝图 + 种子必然出同一份卷。
产出 paper.md / paper.html（可打印，含答题卡）/ answers.md / manifest.json。
"""
import argparse
import html
import json
import random
import sys
from pathlib import Path

TYPE_NAMES = {"choice": "选择题", "fill": "填空题", "judge": "判断题", "solve": "解答题"}
TYPE_ORDER = ["choice", "fill", "judge", "solve"]
CN_NUM = ["一", "二", "三", "四", "五", "六", "七", "八"]
LETTERS = ["A", "B", "C", "D", "E", "F"]


def band_of(difficulty):
    """难度 1-5 → 三档：易（1-2）/ 中（3）/ 难（4-5）。"""
    if difficulty <= 2:
        return "easy"
    if difficulty == 3:
        return "mid"
    return "hard"


BAND_NAMES = {"easy": "易", "mid": "中", "hard": "难"}


# ---------------- 题库加载与体检 ----------------

def load_bank(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("题库文件应为 JSON 数组")
    return data


def validate_bank(bank):
    """返回问题列表（空 = 健康）。"""
    problems = []
    seen_ids, seen_stems = set(), {}
    for i, q in enumerate(bank):
        tag = q.get("id", f"#{i}")
        if not q.get("id"):
            problems.append(f"第 {i + 1} 题缺少 id")
        elif q["id"] in seen_ids:
            problems.append(f"{tag}: id 重复")
        seen_ids.add(q.get("id"))
        stem = (q.get("stem") or "").strip()
        if not stem:
            problems.append(f"{tag}: 题干为空")
        elif stem in seen_stems:
            problems.append(f"{tag}: 题干与 {seen_stems[stem]} 重复")
        seen_stems[stem] = tag
        t = q.get("type")
        if t not in TYPE_NAMES:
            problems.append(f"{tag}: 题型非法（{t}）")
        if t == "choice":
            opts = q.get("options") or []
            if len(opts) < 2:
                problems.append(f"{tag}: 选择题选项不足")
            if (q.get("answer") or "") not in LETTERS[:len(opts)]:
                problems.append(f"{tag}: 选择题答案应为选项字母（现为 {q.get('answer')!r}）")
        if t == "judge" and q.get("answer") not in ("√", "×"):
            problems.append(f"{tag}: 判断题答案应为 √ 或 ×")
        if t in ("fill", "solve") and not (q.get("answer") or "").strip():
            problems.append(f"{tag}: 缺少参考答案")
        d = q.get("difficulty")
        if not isinstance(d, int) or not 1 <= d <= 5:
            problems.append(f"{tag}: 难度应为 1-5 的整数（现为 {d!r}）")
        if not q.get("knowledge"):
            problems.append(f"{tag}: 未标注知识点")
    return problems


# ---------------- 组卷引擎 ----------------

class ComposeError(Exception):
    pass


def _coverage_shortfall(cov, must_cover, min_per):
    return sum(max(0, min_per - cov.get(k, 0)) for k in must_cover)


def _deviation(band_counts, band_targets, cov, must_cover, min_per):
    dev = sum(abs(band_counts[b] - band_targets[b]) for b in band_targets)
    return dev + 4.0 * _coverage_shortfall(cov, must_cover, min_per)


def compose(bank, blueprint):
    """按蓝图选题。返回 (sections, report)；sections = [(section_cfg, [question...]), ...]。"""
    seed = blueprint.get("seed", 0)
    rng = random.Random(seed)
    excluded = set(blueprint.get("exclude_ids", []))
    sections_cfg = blueprint.get("sections", [])
    total_n = sum(s["count"] for s in sections_cfg)
    if total_n == 0:
        raise ComposeError("蓝图没有任何题型配额")
    mix = blueprint.get("difficulty_mix", {"easy": 0.5, "mid": 0.3, "hard": 0.2})
    band_targets = {b: mix.get(b, 0) * total_n for b in ("easy", "mid", "hard")}
    know_cfg = blueprint.get("knowledge", {})
    must_cover = know_cfg.get("must_cover", [])
    min_per = know_cfg.get("min_per_point", 0)

    by_type = {}
    for q in bank:
        by_type.setdefault(q["type"], []).append(q)

    used = set()
    band_counts = {"easy": 0, "mid": 0, "hard": 0}
    cov = {}
    warnings = []
    picked = []  # (section_idx, question)

    def cov_gain(q):
        g = 0.0
        for k in q.get("knowledge", []):
            if k in must_cover:
                lack = min_per - cov.get(k, 0)
                g += 2.0 * lack if lack > 0 else 0.15
            else:
                g += 0.05
        return g

    def take(section_idx, q):
        used.add(q["id"])
        band_counts[band_of(q["difficulty"])] += 1
        for k in q.get("knowledge", []):
            cov[k] = cov.get(k, 0) + 1
        picked.append((section_idx, q))

    # 1) 贪心配平：逐个 section、逐题挑增益最高者
    for si, sec in enumerate(sections_cfg):
        pool_all = [q for q in by_type.get(sec["type"], []) if q["id"] not in excluded]
        for _ in range(sec["count"]):
            pool = [q for q in pool_all if q["id"] not in used]
            if not pool:
                warnings.append(f"{TYPE_NAMES.get(sec['type'], sec['type'])}题库不足："
                                f"需要 {sec['count']} 题，实际选到 {sum(1 for s, _ in picked if s == si)} 题")
                break
            best, best_gain = None, None
            for q in pool:
                b = band_of(q["difficulty"])
                bg = (band_targets[b] - band_counts[b]) / total_n
                gain = cov_gain(q) + 2.5 * bg + rng.random()
                if best_gain is None or gain > best_gain:
                    best, best_gain = q, gain
            take(si, best)

    # 2) 交换改进：同题型互换，降低难度偏差 + 覆盖缺口
    sel_ids = {q["id"] for _, q in picked}
    for _pass in range(60):
        cur = _deviation(band_counts, band_targets, cov, must_cover, min_per)
        if cur <= 0.01:
            break
        improved = False
        rest = [q for q in bank if q["id"] not in sel_ids and q["id"] not in excluded]
        out_list = [q for _, q in picked]
        for out_q in out_list:
            swap_done = False
            for in_q in rest:
                if in_q["type"] != out_q["type"]:
                    continue
                bc = dict(band_counts)
                bc[band_of(out_q["difficulty"])] -= 1
                bc[band_of(in_q["difficulty"])] += 1
                cv = dict(cov)
                for k in out_q.get("knowledge", []):
                    cv[k] = cv.get(k, 0) - 1
                for k in in_q.get("knowledge", []):
                    cv[k] = cv.get(k, 0) + 1
                if _deviation(bc, band_targets, cv, must_cover, min_per) < cur - 1e-9:
                    idx = next(i for i, (_, q) in enumerate(picked) if q["id"] == out_q["id"])
                    picked[idx] = (picked[idx][0], in_q)
                    sel_ids.discard(out_q["id"])
                    sel_ids.add(in_q["id"])
                    band_counts, cov = bc, cv
                    improved = swap_done = True
                    break
            if swap_done:
                break
        if not improved:
            break

    # 3) 组装 sections（节内按难度升序，像真实试卷由易到难）
    sections = []
    for si, sec in enumerate(sections_cfg):
        qs = [q for s, q in picked if s == si]
        qs.sort(key=lambda q: (q["difficulty"], q["id"]))
        sections.append((sec, qs))

    short = _coverage_shortfall(cov, must_cover, min_per)
    if short > 0:
        lacking = [k for k in must_cover if cov.get(k, 0) < min_per]
        warnings.append(f"知识点覆盖未达标：{'、'.join(lacking)} 未达到每点至少 {min_per} 题")
    total_score = sum(sec["score_each"] * len(qs) for sec, qs in sections)
    report = {
        "title": blueprint.get("title", "试卷"),
        "seed": seed,
        "question_count": sum(len(qs) for _, qs in sections),
        "total_score": total_score,
        "band_actual": {b: band_counts[b] for b in band_counts},
        "band_target": {b: round(band_targets[b], 1) for b in band_targets},
        "coverage": {k: cov.get(k, 0) for k in sorted(cov)},
        "warnings": warnings,
    }
    return sections, report


# ---------------- 导出 ----------------

def flatten(sections):
    """连续编号：返回 [(no, sec, q), ...]。"""
    out, no = [], 0
    for sec, qs in sections:
        for q in qs:
            no += 1
            out.append((no, sec, q))
    return out


def render_paper_md(sections, report):
    lines = [f"# {report['title']}", "",
             f"（全卷共 {report['question_count']} 题，满分 {report['total_score']} 分）", ""]
    flat = flatten(sections)
    idx = 0
    for si, (sec, qs) in enumerate(sections):
        if not qs:
            continue
        lines.append(f"## {CN_NUM[si]}、{TYPE_NAMES[sec['type']]}"
                     f"（共 {len(qs)} 题，每题 {sec['score_each']} 分）")
        lines.append("")
        for q in qs:
            idx += 1
            no = flat[idx - 1][0]
            lines.append(f"{no}. {q['stem']}")
            if q["type"] == "choice":
                opts = q.get("options", [])
                for j in range(0, len(opts), 2):
                    pair = opts[j:j + 2]
                    lines.append("　".join(f"{LETTERS[j + k]}. {t}" for k, t in enumerate(pair)))
            lines.append("")
    return "\n".join(lines)


def render_answers_md(sections, report):
    lines = [f"# {report['title']} · 参考答案", ""]
    idx = 0
    for sec, qs in sections:
        for q in qs:
            idx += 1
            line = f"{idx}. {q.get('answer', '')}"
            if q.get("analysis"):
                line += f"　【解析】{q['analysis']}"
            lines.append(line)
    return "\n".join(lines) + "\n"


def _esc(s):
    return html.escape(str(s), quote=True)


def render_html(sections, report):
    flat = flatten(sections)
    parts = ["""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  body { font-family: "Songti SC", "SimSun", serif; color: #111; max-width: 760px; margin: 0 auto; line-height: 1.75; }
  h1 { text-align: center; font-size: 21px; margin: 6px 0 2px; }
  .meta { text-align: center; font-size: 13px; color: #333; }
  .info { display: flex; justify-content: space-between; font-size: 13.5px; border-bottom: 2px solid #111; padding: 6px 0; margin-bottom: 10px; }
  h2 { font-size: 15.5px; margin: 16px 0 6px; }
  .q { margin: 0 0 8px; }
  .opts { margin-left: 1.6em; font-size: 14.5px; }
  .opts span { display: inline-block; min-width: 45%; }
  .card { border: 1.5px solid #111; padding: 8px 10px; margin: 12px 0; }
  .card h3 { margin: 0 0 6px; font-size: 14px; }
  .card table { border-collapse: collapse; width: 100%; font-size: 13px; }
  .card td { border: 1px solid #999; padding: 3px 6px; text-align: center; }
  @media print { body { max-width: none; } }
</style></head><body>""".replace("__TITLE__", _esc(report["title"]))]
    parts.append(f"<h1>{_esc(report['title'])}</h1>")
    parts.append(f"<p class=\"meta\">（全卷共 {report['question_count']} 题，满分 {report['total_score']} 分）</p>")
    parts.append("<div class=\"info\"><span>学校：____________</span><span>班级：____________</span>"
                 "<span>姓名：____________</span><span>学号：____________</span><span>得分：________</span></div>")
    objective = [(no, q) for no, sec, q in flat if q["type"] in ("choice", "judge")]
    if objective:
        parts.append("<div class=\"card\"><h3>答题卡（客观题请在此作答）</h3><table>")
        for r in range(0, len(objective), 5):
            row = objective[r:r + 5]
            cells = []
            for no, q in row:
                marks = "A○ B○ C○ D○" if q["type"] == "choice" else "√○ ×○"
                cells.append(f"<td>{no}. {marks}</td>")
            cells += ["<td></td>"] * (5 - len(cells))
            parts.append("<tr>" + "".join(cells) + "</tr>")
        parts.append("</table></div>")
    idx = 0
    for si, (sec, qs) in enumerate(sections):
        if not qs:
            continue
        parts.append(f"<h2>{CN_NUM[si]}、{_esc(TYPE_NAMES[sec['type']])}"
                     f"（共 {len(qs)} 题，每题 {sec['score_each']} 分）</h2>")
        for q in qs:
            idx += 1
            no = flat[idx - 1][0]
            parts.append(f"<p class=\"q\">{no}. {_esc(q['stem'])}</p>")
            if q["type"] == "choice":
                opts = "".join(f"<span>{LETTERS[j]}. {_esc(t)}</span>"
                               for j, t in enumerate(q.get("options", [])))
                parts.append(f"<p class=\"opts\">{opts}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def build(bank_path, blueprint_path, out_dir):
    bank = load_bank(bank_path)
    problems = validate_bank(bank)
    if problems:
        raise ComposeError("题库体检未通过：\n" + "\n".join("  - " + p for p in problems[:20]))
    blueprint = json.loads(Path(blueprint_path).read_text(encoding="utf-8"))
    sections, report = compose(bank, blueprint)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "paper.md").write_text(render_paper_md(sections, report), encoding="utf-8")
    (out / "paper.html").write_text(render_html(sections, report), encoding="utf-8")
    (out / "answers.md").write_text(render_answers_md(sections, report), encoding="utf-8")
    manifest = dict(report)
    manifest["items"] = [
        {"no": no, "id": q["id"], "type": q["type"], "score": sec["score_each"],
         "knowledge": q.get("knowledge", []), "difficulty": q["difficulty"]}
        for no, sec, q in flatten(sections)
    ]
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def print_report(report):
    print(f"《{report['title']}》组卷完成：{report['question_count']} 题，满分 {report['total_score']} 分"
          f"（种子 {report['seed']}）")
    ba, bt = report["band_actual"], report["band_target"]
    print("难度分布 实际/目标： " + "，".join(
        f"{BAND_NAMES[b]} {ba[b]}/{bt[b]}" for b in ("easy", "mid", "hard")))
    print("知识点覆盖：" + "，".join(f"{k}×{v}" for k, v in report["coverage"].items()))
    for w in report["warnings"]:
        print("⚠️ " + w)
    if not report["warnings"]:
        print("✅ 全部蓝图指标达标")


# ---------------- 命令行 ----------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="ExamForge 智能组卷工作台")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="用自带示例题库与蓝图一键出卷")
    d.add_argument("--out", default="out")
    b = sub.add_parser("build", help="按题库 + 蓝图出卷")
    b.add_argument("--bank", required=True)
    b.add_argument("--blueprint", required=True)
    b.add_argument("--out", default="out")
    v = sub.add_parser("validate", help="题库体检")
    v.add_argument("--bank", required=True)
    args = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    try:
        if args.cmd == "demo":
            report = build(here / "bank.sample.json", here / "blueprint.sample.json", args.out)
            print_report(report)
            print(f"产出在 {args.out}/ ：paper.md / paper.html / answers.md / manifest.json")
        elif args.cmd == "build":
            report = build(args.bank, args.blueprint, args.out)
            print_report(report)
            print(f"产出在 {args.out}/ ：paper.md / paper.html / answers.md / manifest.json")
        elif args.cmd == "validate":
            bank = load_bank(args.bank)
            problems = validate_bank(bank)
            if problems:
                print(f"题库共 {len(bank)} 题，发现 {len(problems)} 个问题：")
                for p in problems:
                    print("  - " + p)
                return 1
            types = {}
            for q in bank:
                types[q["type"]] = types.get(q["type"], 0) + 1
            print(f"题库健康：共 {len(bank)} 题（" +
                  "，".join(f"{TYPE_NAMES[t]} {n}" for t, n in sorted(types.items())) + "），无重复、无缺项。")
    except ComposeError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
