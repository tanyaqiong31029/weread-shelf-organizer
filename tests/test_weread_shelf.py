#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weread-shelf-organizer 离线回归测试 — 全部 mock, 无网络依赖。

运行: python3 -m unittest discover -s tests -v
"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import weread_shelf as W  # noqa: E402

RULES = {
    "groups": [{"name": "01 成长学习", "description": "成长"},
               {"name": "03 商业经济", "description": "商业"},
               {"name": "09 类型小说", "description": "小说"}],
    "category_map": {"经济理财-商业": "03 商业经济",
                     "精品小说": "09 类型小说"},
}


def ns(**kw):
    return argparse.Namespace(**kw)


class ClassifyTests(unittest.TestCase):
    """回归: classify() 元数不一致导致 plan 在首本待复核书处崩溃。"""

    def test_classify_always_returns_3_tuple(self):
        import tempfile as _t
        with _t.TemporaryDirectory() as d:
            rp = Path(d) / "r.json"
            rp.write_text(json.dumps(RULES), encoding="utf-8")
            rules = W.load_rules(str(rp))
        stats = {}
        books = [
            {"category": ""},                          # 空分类
            {"category": "经济理财-商业"},               # 完整命中
            {"category": "精品小说-悬疑推理"},            # 主栏目命中
            {"category": "玄学-占卜"},                   # 未配置映射
            {},                                        # 无 category 字段
        ]
        for b in books:
            out = W.classify(b, rules, stats)
            self.assertEqual(len(out), 3, f"classify 必须恒返回 3 元组: {b} → {out}")
            g, basis, conf = out
            self.assertIsInstance(basis, str)
            self.assertIsInstance(conf, float)

    def test_classify_unmapped_book_unpack_safe(self):
        """用户报告的精确崩溃场景: 未映射分类书按 g, basis, _ 解包。"""
        import tempfile as _t
        with _t.TemporaryDirectory() as d:
            rp = Path(d) / "r.json"
            rp.write_text(json.dumps(RULES), encoding="utf-8")
            rules = W.load_rules(str(rp))
        g, basis, _ = W.classify({"category": "玄学-占卜"}, rules, {})
        self.assertIsNone(g)
        self.assertIn("未配置映射", basis)

    def test_confidence_by_match_type(self):
        import tempfile as _t
        with _t.TemporaryDirectory() as d:
            rp = Path(d) / "r.json"
            rp.write_text(json.dumps(RULES), encoding="utf-8")
            rules = W.load_rules(str(rp))
        _, _, full = W.classify({"category": "经济理财-商业"}, rules, {})
        _, _, head = W.classify({"category": "精品小说-悬疑推理"}, rules, {})
        _, _, none = W.classify({"category": "玄学-占卜"}, rules, {})
        self.assertEqual(full, rules["match_confidence"]["full_match"])
        self.assertEqual(head, rules["match_confidence"]["head_match"])
        self.assertEqual(none, 0.0)

    def test_load_rules_rejects_duplicate_groups(self):
        import tempfile as _t
        bad = {"groups": [{"name": "x"}, {"name": "x"}], "category_map": {}}
        with _t.TemporaryDirectory() as d:
            rp = Path(d) / "r.json"
            rp.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(AssertionError):
                W.load_rules(str(rp))


class PlanTests(unittest.TestCase):
    """端到端(离线): plan 必须能带着「待复核」书正常产出计划。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rp = Path(self.tmp.name) / "rules.json"
        rp.write_text(json.dumps(RULES), encoding="utf-8")
        self.rules_path = str(rp)
        self.plan_path = str(Path(self.tmp.name) / "plan.json")
        self.shelf = {"books": [
            {"bookId": "1", "title": "管理学", "author": "a", "category": "经济理财-商业"},
            {"bookId": "2", "title": "神秘书", "author": "b", "category": "玄学-占卜"},
            {"bookId": "3", "title": "导入书", "author": "c", "category": ""},
        ], "archive": [{"name": "03 商业经济", "archiveId": 303, "bookIds": []}]}

    def tearDown(self):
        self.tmp.cleanup()

    def _run_plan(self, **kw):
        with mock.patch.object(W, "get_cred", return_value={"vid": "1", "skey": "s",
                                                            "v": "1", "ua": "u"}), \
             mock.patch.object(W, "sync_shelf", return_value=self.shelf):
            W.cmd_plan(ns(rules=self.rules_path, baseline=kw.get("baseline"),
                          output=self.plan_path, full=False, dry_run=False))

    def test_plan_with_review_books_no_crash(self):
        """回归: 存在未映射分类书时 plan 不崩溃, 且正确分流 moves/review。"""
        self._run_plan()
        plan = json.load(open(self.plan_path, encoding="utf-8"))
        self.assertEqual([m["bookId"] for m in plan["moves"]], ["1"])
        self.assertEqual({r["bookId"] for r in plan["review"]}, {"2", "3"})
        self.assertEqual(plan["moves"][0]["to"], "03 商业经济")
        r2 = next(r for r in plan["review"] if r["bookId"] == "2")
        self.assertIn("未配置映射", r2["hint"])

    def test_plan_low_confidence_goes_to_review_with_suggest(self):
        """head_match(0.75) 低于阈值(0.8)时应进复核并附候选建议。"""
        rules = dict(RULES)
        rules["min_confidence"] = 0.8
        rp = Path(self.tmp.name) / "rules80.json"
        rp.write_text(json.dumps(rules), encoding="utf-8")
        self.rules_path = str(rp)
        # 把书 1 换成主栏目命中(0.75 < 0.8)
        self.shelf["books"][0]["category"] = "精品小说-悬疑推理"
        self._run_plan()
        plan = json.load(open(self.plan_path, encoding="utf-8"))
        self.assertEqual(plan["moves"], [])
        r = next(r for r in plan["review"] if r["bookId"] == "1")
        self.assertEqual(r["suggest"], "09 类型小说")
        self.assertIn("阈值", r["hint"])

    def test_plan_baseline_takes_precedence(self):
        base = Path(self.tmp.name) / "base.csv"
        base.write_text("\ufeffbookId,target_group\n2,01 成长学习\n",
                        encoding="utf-8")
        self._run_plan(baseline=str(base))
        plan = json.load(open(self.plan_path, encoding="utf-8"))
        m = next(m for m in plan["moves"] if m["bookId"] == "2")
        self.assertEqual(m["to"], "01 成长学习")
        self.assertEqual(m["confidence"], 1.0)


class VerifyTests(unittest.TestCase):
    """verify 必须校验「正确分组」, 而非「任意目标分组」。"""

    SHELF = {"books": [], "archive": [
        {"name": "01 成长学习", "archiveId": 1, "bookIds": ["1"]},
        {"name": "03 商业经济", "archiveId": 3, "bookIds": ["2"]},
    ]}

    def test_wrong_group_is_flagged(self):
        with mock.patch.object(W, "sync_shelf", return_value=self.SHELF), \
             mock.patch.object(W.time, "sleep"):
            wrong = W._verify({"vid": "1", "skey": "s", "v": "1", "ua": "u"},
                              {"1": "03 商业经济", "2": "03 商业经济"})
        self.assertEqual(len(wrong), 1)
        bid, want, got = wrong[0]
        self.assertEqual((bid, want, got), ("1", "03 商业经济", "01 成长学习"))

    def test_correct_group_passes(self):
        with mock.patch.object(W, "sync_shelf", return_value=self.SHELF), \
             mock.patch.object(W.time, "sleep"):
            wrong = W._verify({"vid": "1", "skey": "s", "v": "1", "ua": "u"},
                              {"2": "03 商业经济"})
        self.assertEqual(wrong, [])


class CredTests(unittest.TestCase):
    def test_env_credentials_used_without_client(self):
        env = {"WEREAD_VID": "12345678", "WEREAD_SKEY": "abcDEF12"}
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch.object(W, "extract_cred") as ex, \
             mock.patch.object(W, "http_json", return_value={"errcode": 0}) as hj:
            cred = W.get_cred()
        self.assertEqual(cred["vid"], "12345678")
        self.assertEqual(cred["skey"], "abcDEF12")
        ex.assert_not_called()                      # 不应触碰客户端日志
        self.assertIn("/shelf/sync", hj.call_args[0][0])

    def test_env_invalid_falls_back_then_exits(self):
        import urllib.error
        err = urllib.error.HTTPError("u", 401, "", None, None)
        with mock.patch.dict("os.environ", {"WEREAD_VID": "1", "WEREAD_SKEY": "x"},
                             clear=False), \
             mock.patch.object(W, "http_json", side_effect=err), \
             mock.patch.object(W, "extract_cred", return_value=None):
            with self.assertRaises(SystemExit) as cm:
                W.get_cred(retry=1)
        self.assertEqual(cm.exception.code, 2)


class MoveTests(unittest.TestCase):
    def test_batching_40_per_call(self):
        calls = []

        def fake_http(url, payload=None, hdrs=None, timeout=30):
            calls.append(payload["bookIds"])
            return {"succ": 1}

        aid = {"03 商业经济": 303}
        ids = [str(i) for i in range(55)]  # 55 本 → 40 + 15 两批
        with mock.patch.object(W, "http_json", side_effect=fake_http), \
             mock.patch.object(W.time, "sleep"):
            moved, failed = W._do_moves({"v": "1"}, {"03 商业经济": ids}, aid)
        self.assertEqual([len(c) for c in calls], [40, 15])
        self.assertEqual(len(moved), 55)
        self.assertEqual(failed, [])

    def test_missing_group_not_moved(self):
        with mock.patch.object(W, "http_json") as hj, \
             mock.patch.object(W.time, "sleep"):
            moved, failed = W._do_moves({"v": "1"}, {"09 类型小说": ["1", "2"]}, {})
        hj.assert_not_called()
        self.assertEqual(moved, [])
        self.assertEqual(failed, ["1", "2"])


class BaselineTests(unittest.TestCase):
    def test_load_baseline_bom_and_spaces(self):
        import tempfile as _t
        with _t.TemporaryDirectory() as d:
            p = Path(d) / "b.csv"
            p.write_text("\ufeffbookId,target_group\n 123, 03 商业经济 \nxx,skip\n",
                         encoding="utf-8")
            base = W.load_baseline(str(p))
        self.assertEqual(base, {"123": "03 商业经济"})


if __name__ == "__main__":
    unittest.main()
