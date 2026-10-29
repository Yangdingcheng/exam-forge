# -*- coding: utf-8 -*-
"""ExamForge 测试（标准库 unittest）：python tests.py"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main as ef

HERE = Path(__file__).resolve().parent
BANK = ef.load_bank(HERE / "bank.sample.json")
BP = json.loads((HERE / "blueprint.sample.json").read_text(encoding="utf-8"))


class TestValidate(unittest.TestCase):
    def test_sample_bank_clean(self):
        self.assertEqual(ef.validate_bank(BANK), [])

    def test_catches_problems(self):
        bad = [dict(BANK[0]), dict(BANK[0])]
        bad[1]["id"] = "dup-stem"
        bad.append({"id": "x1", "type": "choice", "stem": "题干？", "options": ["1", "2"],
                    "answer": "Z", "knowledge": ["有理数"], "difficulty": 9})
        bad.append({"id": "x2", "type": "judge", "stem": "对吗？", "answer": "对",
                    "knowledge": [], "difficulty": 2})
        problems = ef.validate_bank(bad)
        text = "\n".join(problems)
        self.assertIn("题干与", text)
        self.assertIn("选项字母", text)
        self.assertIn("1-5", text)
        self.assertIn("√ 或 ×", text)
        self.assertIn("知识点", text)

    def test_band_mapping(self):
        self.assertEqual([ef.band_of(d) for d in (1, 2, 3, 4, 5)],
                         ["easy", "easy", "mid", "hard", "hard"])


class TestCompose(unittest.TestCase):
    def test_quotas_and_score(self):
        sections, report = ef.compose(BANK, BP)
        counts = {sec["type"]: len(qs) for sec, qs in sections}
        self.assertEqual(counts, {"choice": 8, "fill": 8, "judge": 6, "solve": 4})
        self.assertEqual(report["question_count"], 26)
        self.assertEqual(report["total_score"], 100)

    def test_seed_reproducible(self):
        s1, _ = ef.compose(BANK, BP)
        s2, _ = ef.compose(BANK, BP)
        ids1 = [q["id"] for _, qs in s1 for q in qs]
        ids2 = [q["id"] for _, qs in s2 for q in qs]
        self.assertEqual(ids1, ids2)

    def test_seed_changes_paper(self):
        bp2 = dict(BP, seed=7)
        s1, _ = ef.compose(BANK, BP)
        s2, _ = ef.compose(BANK, bp2)
        ids1 = {q["id"] for _, qs in s1 for q in qs}
        ids2 = {q["id"] for _, qs in s2 for q in qs}
        self.assertNotEqual(ids1, ids2)

    def test_coverage_met(self):
        _, report = ef.compose(BANK, BP)
        for k in BP["knowledge"]["must_cover"]:
            self.assertGreaterEqual(report["coverage"].get(k, 0),
                                    BP["knowledge"]["min_per_point"], k)
        self.assertEqual(report["warnings"], [])

    def test_difficulty_close_to_target(self):
        _, report = ef.compose(BANK, BP)
        dev = sum(abs(report["band_actual"][b] - report["band_target"][b])
                  for b in ("easy", "mid", "hard"))
        self.assertLessEqual(dev, 4.0, report["band_actual"])

    def test_no_duplicate_questions(self):
        sections, _ = ef.compose(BANK, BP)
        ids = [q["id"] for _, qs in sections for q in qs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_exclude_ids(self):
        bp = dict(BP, exclude_ids=["num-01", "num-02", "poly-01"])
        sections, _ = ef.compose(BANK, bp)
        ids = {q["id"] for _, qs in sections for q in qs}
        self.assertTrue(ids.isdisjoint({"num-01", "num-02", "poly-01"}))

    def test_shortfall_warns_not_crashes(self):
        bp = json.loads(json.dumps(BP))
        bp["sections"][2]["count"] = 20  # 判断题题库只有 7 道
        sections, report = ef.compose(BANK, bp)
        self.assertTrue(any("题库不足" in w for w in report["warnings"]))
        counts = {sec["type"]: len(qs) for sec, qs in sections}
        self.assertEqual(counts["judge"], 7)

    def test_section_sorted_by_difficulty(self):
        sections, _ = ef.compose(BANK, BP)
        for _, qs in sections:
            ds = [q["difficulty"] for q in qs]
            self.assertEqual(ds, sorted(ds))


class TestExport(unittest.TestCase):
    def test_build_writes_four_files(self):
        with tempfile.TemporaryDirectory() as td:
            report = ef.build(HERE / "bank.sample.json", HERE / "blueprint.sample.json", td)
            for name in ("paper.md", "paper.html", "answers.md", "manifest.json"):
                self.assertTrue((Path(td) / name).exists(), name)
            manifest = json.loads((Path(td) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["items"]), 26)
            self.assertEqual(len({i["id"] for i in manifest["items"]}), 26)
            paper = (Path(td) / "paper.md").read_text(encoding="utf-8")
            self.assertIn("七年级数学", paper)
            self.assertIn("一、选择题", paper)
            answers = (Path(td) / "answers.md").read_text(encoding="utf-8")
            self.assertEqual(sum(1 for ln in answers.splitlines() if ln and ln[0].isdigit()), 26)
            self.assertIn("【解析】", answers)
            page = (Path(td) / "paper.html").read_text(encoding="utf-8")
            self.assertIn("答题卡", page)
            self.assertIn("姓名", page)
            self.assertEqual(report["total_score"], 100)

    def test_html_escapes_stem(self):
        bank = [{"id": "e1", "type": "choice", "stem": "1 < 2 对吗？<script>",
                 "options": ["对", "错", "不知", "都行"], "answer": "A",
                 "knowledge": ["实数"], "difficulty": 1}]
        bp = {"title": "T", "seed": 1,
              "sections": [{"type": "choice", "count": 1, "score_each": 5}]}
        sections, report = ef.compose(bank, bp)
        page = ef.render_html(sections, report)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main(verbosity=1)
