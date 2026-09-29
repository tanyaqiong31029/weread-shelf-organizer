#!/usr/bin/env python3
"""weread-shelf-organizer 离线回归测试 — 全部 mock, 无网络依赖。

运行: python3 -m unittest discover -s tests -v
"""

import argparse
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import urllib.error

import weread_shelf as W  # noqa: E402

RULES = {
    "groups": [
        {"name": "01 成长学习", "description": "成长"},
        {"name": "03 商业经济", "description": "商业"},
        {"name": "09 类型小说", "description": "小说"},
    ],
    "category_map": {"经济理财-商业": "03 商业经济", "精品小说": "09 类型小说"},
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
            {"category": ""},  # 空分类
            {"category": "经济理财-商业"},  # 完整命中
            {"category": "精品小说-悬疑推理"},  # 主栏目命中
            {"category": "玄学-占卜"},  # 未配置映射
            {},  # 无 category 字段
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
        self.shelf = {
            "books": [
                {"bookId": "1", "title": "管理学", "author": "a", "category": "经济理财-商业"},
                {"bookId": "2", "title": "神秘书", "author": "b", "category": "玄学-占卜"},
                {"bookId": "3", "title": "导入书", "author": "c", "category": ""},
            ],
            "archive": [{"name": "03 商业经济", "archiveId": 303, "bookIds": []}],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _run_plan(self, **kw):
        with (
            mock.patch.object(
                W, "get_cred", return_value={"vid": "1", "skey": "s", "v": "1", "ua": "u"}
            ),
            mock.patch.object(W, "sync_shelf", return_value=self.shelf),
        ):
            W.cmd_plan(
                ns(
                    rules=self.rules_path,
                    baseline=kw.get("baseline"),
                    output=self.plan_path,
                    dry_run=False,
                    reorganize=kw.get("reorganize", False),
                    source_group=kw.get("source_group"),
                )
            )

    def test_plan_with_review_books_no_crash(self):
        """回归: 存在未映射分类书时 plan 不崩溃, 且正确分流 moves/review。"""
        self._run_plan()
        with open(self.plan_path, encoding="utf-8") as f:
            plan = json.load(f)
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
        with open(self.plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual(plan["moves"], [])
        r = next(r for r in plan["review"] if r["bookId"] == "1")
        self.assertEqual(r["suggest"], "09 类型小说")
        self.assertIn("阈值", r["hint"])

    def test_plan_baseline_takes_precedence(self):
        base = Path(self.tmp.name) / "base.csv"
        base.write_text("\ufeffbookId,target_group\n2,01 成长学习\n", encoding="utf-8")
        self._run_plan(baseline=str(base))
        with open(self.plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        m = next(m for m in plan["moves"] if m["bookId"] == "2")
        self.assertEqual(m["to"], "01 成长学习")
        self.assertEqual(m["confidence"], 1.0)


class VerifyTests(unittest.TestCase):
    """verify 必须校验「正确分组」, 而非「任意目标分组」。"""

    SHELF = {
        "books": [],
        "archive": [
            {"name": "01 成长学习", "archiveId": 1, "bookIds": ["1"]},
            {"name": "03 商业经济", "archiveId": 3, "bookIds": ["2"]},
        ],
    }

    def test_wrong_group_is_flagged(self):
        with (
            mock.patch.object(W, "sync_shelf", return_value=self.SHELF),
            mock.patch.object(W.time, "sleep"),
        ):
            wrong = W._verify(
                {"vid": "1", "skey": "s", "v": "1", "ua": "u"},
                {"1": "03 商业经济", "2": "03 商业经济"},
            )
        self.assertEqual(len(wrong), 1)
        bid, want, got = wrong[0]
        self.assertEqual((bid, want, got), ("1", "03 商业经济", "01 成长学习"))

    def test_correct_group_passes(self):
        with (
            mock.patch.object(W, "sync_shelf", return_value=self.SHELF),
            mock.patch.object(W.time, "sleep"),
        ):
            wrong = W._verify({"vid": "1", "skey": "s", "v": "1", "ua": "u"}, {"2": "03 商业经济"})
        self.assertEqual(wrong, [])


class CredTests(unittest.TestCase):
    def test_env_credentials_used_without_client(self):
        env = {"WEREAD_VID": "12345678", "WEREAD_SKEY": "abcDEF12"}
        with (
            mock.patch.dict("os.environ", env, clear=False),
            mock.patch.object(W, "extract_cred") as ex,
            mock.patch.object(W, "http_json", return_value={"errcode": 0}) as hj,
        ):
            cred = W.get_cred()
        self.assertEqual(cred["vid"], "12345678")
        self.assertEqual(cred["skey"], "abcDEF12")
        ex.assert_not_called()  # 不应触碰客户端日志
        self.assertIn("/shelf/sync", hj.call_args[0][0])

    def test_env_invalid_falls_back_then_exits(self):
        import urllib.error

        err = urllib.error.HTTPError("u", 401, "", None, None)
        with (
            mock.patch.dict("os.environ", {"WEREAD_VID": "1", "WEREAD_SKEY": "x"}, clear=False),
            mock.patch.object(W, "http_json", side_effect=err),
            mock.patch.object(W, "extract_cred", return_value=None),
        ):
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
        with (
            mock.patch.object(W, "http_json", side_effect=fake_http),
            mock.patch.object(W.time, "sleep"),
        ):
            moved, failed, batches = W._do_moves({"v": "1"}, {"03 商业经济": ids}, aid)
        self.assertEqual([len(c) for c in calls], [40, 15])
        self.assertEqual(len(moved), 55)
        self.assertEqual(failed, [])
        self.assertEqual([b["books"] for b in batches], [40, 15])
        self.assertTrue(all(b["ok"] for b in batches))

    def test_missing_group_not_moved(self):
        with mock.patch.object(W, "http_json") as hj, mock.patch.object(W.time, "sleep"):
            moved, failed, batches = W._do_moves({"v": "1"}, {"09 类型小说": ["1", "2"]}, {})
        hj.assert_not_called()
        self.assertEqual(moved, [])
        self.assertEqual(failed, ["1", "2"])
        self.assertEqual(batches[0]["reason"], "group_missing")

    def test_failed_batch_records_api_error_summary(self):
        """批次失败时, 批次摘要必须带上 API 响应错误摘要。"""

        def fake_http(url, payload=None, hdrs=None, timeout=30):
            return {"errcode": -2014, "errmsg": "请求过于频繁"}

        with (
            mock.patch.object(
                W, "get_cred", return_value={"vid": "1", "skey": "s", "v": "1", "ua": "u"}
            ),
            mock.patch.object(W, "http_json", side_effect=fake_http),
            mock.patch.object(W.time, "sleep"),
        ):
            moved, failed, batches = W._do_moves(
                {"v": "1"}, {"09 类型小说": ["1", "2"]}, {"09 类型小说": 9}
            )
        self.assertEqual(failed, ["1", "2"])
        self.assertFalse(batches[0]["ok"])
        self.assertIn("-2014", batches[0]["error"])
        self.assertIn("请求过于频繁", batches[0]["error"])


class BaselineTests(unittest.TestCase):
    def test_load_baseline_bom_and_spaces(self):
        import tempfile as _t

        with _t.TemporaryDirectory() as d:
            p = Path(d) / "b.csv"
            p.write_text(
                "\ufeffbookId,target_group\n 123, 03 商业经济 \nxx,skip\n", encoding="utf-8"
            )
            base = W.load_baseline(str(p))
        self.assertEqual(base, {"123": "03 商业经济"})


class ReorganizePlanTests(unittest.TestCase):
    """安全回归: 重组模式只能动显式白名单里的来源分组。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rp = Path(self.tmp.name) / "rules.json"
        rp.write_text(json.dumps(RULES), encoding="utf-8")
        self.rules_path = str(rp)
        self.plan_path = str(Path(self.tmp.name) / "plan.json")
        # 书1未分组; 书2在旧榜单A; 书3在旧榜单B; 分类全部命中映射
        self.shelf = {
            "books": [
                {"bookId": "1", "title": "未分组书", "author": "a", "category": "经济理财-商业"},
                {"bookId": "2", "title": "榜单书A", "author": "b", "category": "经济理财-商业"},
                {"bookId": "3", "title": "榜单书B", "author": "c", "category": "经济理财-商业"},
            ],
            "archive": [
                {"name": "旧榜单A", "archiveId": 11, "bookIds": ["2"]},
                {"name": "旧榜单B", "archiveId": 12, "bookIds": ["3"]},
                {"name": "03 商业经济", "archiveId": 303, "bookIds": []},
            ],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self, **kw):
        with (
            mock.patch.object(
                W, "get_cred", return_value={"vid": "1", "skey": "s", "v": "1", "ua": "u"}
            ),
            mock.patch.object(W, "sync_shelf", return_value=self.shelf),
        ):
            W.cmd_plan(
                ns(
                    rules=self.rules_path,
                    baseline=None,
                    dry_run=False,
                    output=self.plan_path,
                    reorganize=kw.get("reorganize", False),
                    source_group=kw.get("source_group"),
                )
            )
        with open(self.plan_path, encoding="utf-8") as f:
            return json.load(f)

    def test_default_never_touches_grouped_books(self):
        plan = self._plan()
        self.assertEqual([m["bookId"] for m in plan["moves"]], ["1"])
        self.assertEqual(plan["moves"][0]["from"], None)

    def test_reorganize_without_whitelist_is_incremental(self):
        plan = self._plan(reorganize=True, source_group="")
        self.assertEqual([m["bookId"] for m in plan["moves"]], ["1"])

    def test_reorganize_only_whitelisted_source(self):
        plan = self._plan(reorganize=True, source_group="旧榜单A")
        by_id = {m["bookId"]: m for m in plan["moves"]}
        self.assertIn("1", by_id)
        self.assertEqual(by_id["2"]["from"], "旧榜单A")  # 白名单分组, 记录来源
        self.assertNotIn("3", by_id)  # 非白名单分组不动
        self.assertEqual(plan["source_snapshot"], {"旧榜单A": ["2"]})
        self.assertEqual(plan["mode"], "reorganize")

    def test_reorganize_unknown_source_group_ignored(self):
        plan = self._plan(reorganize=True, source_group="不存在的榜")
        self.assertEqual([m["bookId"] for m in plan["moves"]], ["1"])
        self.assertEqual(plan["source_snapshot"], {})


class FakeShelf:
    """有状态假书架: http_json 的迁移会真实改变状态, 第二次同步反映迁移结果。"""

    def __init__(self, groups):
        # groups: {name: (archiveId, [bookIds])}
        self.g = {n: {"archiveId": i, "ids": list(ids)} for n, (i, ids) in groups.items()}

    def shelf(self):
        return {
            "books": [],
            "archive": [
                {"name": n, "archiveId": v["archiveId"], "bookIds": list(v["ids"])}
                for n, v in self.g.items()
            ],
        }

    def apply_move(self, ids, name):
        ids = list(ids)
        for v in self.g.values():
            v["ids"] = [x for x in v["ids"] if x not in ids]
        self.g.setdefault(name, {"archiveId": 999, "ids": []})
        self.g[name]["ids"].extend(ids)


class ApplySafetyTests(unittest.TestCase):
    """安全回归: apply 执行前重校验书架状态, 重组迁移必须 --yes,
    迁移失败/核验错位必须以非零退出码结束。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plan_path = str(Path(self.tmp.name) / "plan.json")
        self._write_plan()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_plan(self):
        plan = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "reorganize",
            "total_books": 2,
            "ungrouped": 1,
            "moves": [
                {
                    "bookId": "1",
                    "title": "未分组书",
                    "from": None,
                    "to": "03 商业经济",
                    "basis": "t",
                    "confidence": 1.0,
                },
                {
                    "bookId": "2",
                    "title": "榜单书A",
                    "from": "旧榜单A",
                    "to": "03 商业经济",
                    "basis": "t",
                    "confidence": 1.0,
                },
            ],
            "review": [],
            "skipped_custom_groups": {},
            "source_snapshot": {},
            "group_archive_ids": {"03 商业经济": 303},
            "missing_groups": [],
        }
        Path(self.plan_path).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    def _run_apply(self, groups, yes, lie=False, json_report=None):
        """groups: {分组名: (archiveId, [bookIds])}; lie=True 时接口谎报成功但状态不变。"""
        fs = FakeShelf(groups)
        calls = []

        def fake_http(url, payload=None, hdrs=None, timeout=30):
            calls.append(payload)
            if payload and "bookIds" in payload and not lie:
                fs.apply_move(payload["bookIds"], payload["name"])
            return {"succ": 1}

        with (
            mock.patch.object(
                W, "get_cred", return_value={"vid": "1", "skey": "s", "v": "1", "ua": "u"}
            ),
            mock.patch.object(W, "sync_shelf", side_effect=lambda *a, **k: fs.shelf()),
            mock.patch.object(W, "http_json", side_effect=fake_http),
            mock.patch.object(W.time, "sleep"),
        ):
            W.cmd_apply(ns(plan=self.plan_path, dry_run=False, yes=yes, json_report=json_report))
        return calls, fs

    def test_stale_plan_entries_are_skipped(self):
        """计划生成后书2被移到别的分组 → 该条自动跳过, 只执行仍有效的迁移。"""
        calls, _ = self._run_apply({"旧榜单B": (11, ["2"]), "03 商业经济": (303, [])}, yes=False)
        moved_ids = [i for c in calls for i in c["bookIds"]]
        self.assertEqual(moved_ids, ["1"])

    def test_reorganize_requires_explicit_yes(self):
        """重组迁移(来自已有分组)未加 --yes 时必须拒绝执行, 一本都不能动。"""
        with self.assertRaises(SystemExit) as cm:
            self._run_apply({"旧榜单A": (11, ["2"]), "03 商业经济": (303, [])}, yes=False)
        self.assertEqual(cm.exception.code, 3)

    def test_yes_executes_full_plan_and_verify_passes(self):
        """加 --yes 后执行, 且核验基于「迁移后」的书架状态通过。"""
        calls, fs = self._run_apply({"旧榜单A": (11, ["2"]), "03 商业经济": (303, [])}, yes=True)
        moved_ids = sorted(i for c in calls for i in c["bookIds"])
        self.assertEqual(moved_ids, ["1", "2"])
        self.assertEqual(fs.g["03 商业经济"]["ids"], ["1", "2"])  # 状态真实落位

    def test_verify_failure_exits_nonzero(self):
        """接口谎报成功但状态未变 → 核验错位必须以非零退出码结束。"""
        with self.assertRaises(SystemExit) as cm:
            self._run_apply({"旧榜单A": (11, ["2"]), "03 商业经济": (303, [])}, yes=True, lie=True)
        self.assertEqual(cm.exception.code, 1)

    def test_json_report_written(self):
        rp = str(Path(self.tmp.name) / "report.json")
        self._run_apply(
            {"旧榜单A": (11, ["2"]), "03 商业经济": (303, [])}, yes=True, json_report=rp
        )
        with open(rp, encoding="utf-8") as f:
            report = json.load(f)
        self.assertEqual(report["command"], "apply")
        self.assertEqual(sorted(report["moved"]), ["1", "2"])
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["wrong"], [])


class ReviewSafetyTests(unittest.TestCase):
    """安全回归: review 决定执行前校验当前分组状态, 核验失败非零退出。"""

    def _run_review(self, decisions, groups, lie=False, yes=False):
        fs = FakeShelf(groups)
        calls = []

        def fake_http(url, payload=None, hdrs=None, timeout=30):
            calls.append(payload)
            if payload and "bookIds" in payload and not lie:
                fs.apply_move(payload["bookIds"], payload["name"])
            return {"succ": 1}

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d) / "d.json"
            dp.write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")
            with (
                mock.patch.object(
                    W, "get_cred", return_value={"vid": "1", "skey": "s", "v": "1", "ua": "u"}
                ),
                mock.patch.object(W, "sync_shelf", side_effect=lambda *a, **k: fs.shelf()),
                mock.patch.object(W, "http_json", side_effect=fake_http),
                mock.patch.object(W.time, "sleep"),
            ):
                W.cmd_review(ns(decisions=str(dp), json_report=None, yes=yes))
        return calls, fs

    def test_review_skips_mismatched_state(self):
        """无 from 的决定要求书处于未分组; 书已在分组 → 一本都不动。"""
        calls, _ = self._run_review(
            [{"bookId": "2", "group": "03 商业经济"}],
            {"03 商业经济": (303, []), "旧榜单A": (11, ["2"])},
        )
        self.assertEqual(calls, [])

    def test_review_requires_yes_for_group_sourced(self):
        """回归(评审8): review 移动「来自已有分组」的书必须 --yes, 与 apply 同规则。"""
        with self.assertRaises(SystemExit) as cm:
            self._run_review(
                [{"bookId": "2", "group": "03 商业经济", "from": "旧榜单A"}],
                {"03 商业经济": (303, []), "旧榜单A": (11, ["2"])},
                yes=False,
            )
        self.assertEqual(cm.exception.code, 3)

    def test_review_moves_when_state_matches(self):
        calls, fs = self._run_review(
            [{"bookId": "2", "group": "03 商业经济", "from": "旧榜单A"}],
            {"03 商业经济": (303, []), "旧榜单A": (11, ["2"])},
            yes=True,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["bookIds"], ["2"])
        self.assertEqual(fs.g["03 商业经济"]["ids"], ["2"])

    def test_review_verify_failure_exits_nonzero(self):
        with self.assertRaises(SystemExit) as cm:
            self._run_review(
                [{"bookId": "2", "group": "03 商业经济", "from": "旧榜单A"}],
                {"03 商业经济": (303, []), "旧榜单A": (11, ["2"])},
                lie=True,
                yes=True,
            )
        self.assertEqual(cm.exception.code, 1)

    def test_review_unknown_group_fails_nonzero(self):
        """回归(评审8): 目标分组不存在必须计为失败并非零退出, 不能静默成功。"""
        with self.assertRaises(SystemExit) as cm:
            self._run_review(
                [{"bookId": "2", "group": "不存在的组"}],
                {"03 商业经济": (303, [])},
                yes=True,
            )
        self.assertEqual(cm.exception.code, 1)


class ArchiveGroupTests(unittest.TestCase):
    """回归: 系统分组「归档」是未分组书的承载容器, 必须视同未分组。"""

    def test_snapshot_current_ignores_archive(self):
        shelf = {
            "archive": [
                {"name": "归档", "archiveId": 1, "bookIds": ["9"]},
                {"name": "03 商业经济", "archiveId": 303, "bookIds": ["1"]},
            ]
        }
        actual = W.snapshot_current(shelf)
        self.assertNotIn("9", actual)  # 归档内 = 未分组
        self.assertEqual(actual.get("1"), "03 商业经济")

    def test_apply_treats_archived_as_ungrouped(self):
        """计划时未分组、执行时进了「归档」的书, 仍应正常迁移。"""
        plan = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "incremental",
            "total_books": 1,
            "ungrouped": 1,
            "moves": [
                {
                    "bookId": "9",
                    "title": "归档书",
                    "from": None,
                    "to": "01 成长学习",
                    "basis": "t",
                    "confidence": 1.0,
                }
            ],
            "review": [],
            "skipped_custom_groups": {},
            "source_snapshot": {},
            "group_archive_ids": {"01 成长学习": 101},
            "missing_groups": [],
        }
        with tempfile.TemporaryDirectory() as d:
            pp = Path(d) / "p.json"
            pp.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            fs = FakeShelf({"归档": (1, ["9"]), "01 成长学习": (101, [])})
            calls = []

            def fake_http(url, payload=None, hdrs=None, timeout=30):
                calls.append(payload)
                if payload and "bookIds" in payload:
                    fs.apply_move(payload["bookIds"], payload["name"])
                return {"succ": 1}

            with (
                mock.patch.object(
                    W, "get_cred", return_value={"vid": "1", "skey": "s", "v": "1", "ua": "u"}
                ),
                mock.patch.object(W, "sync_shelf", side_effect=lambda *a, **k: fs.shelf()),
                mock.patch.object(W, "http_json", side_effect=fake_http),
                mock.patch.object(W.time, "sleep"),
            ):
                W.cmd_apply(ns(plan=str(pp), dry_run=False, yes=False, json_report=None))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["bookIds"], ["9"])
        self.assertEqual(fs.g["01 成长学习"]["ids"], ["9"])


class HttpBackoffTests(unittest.TestCase):
    """回归: 429/5xx/网络超时按指数退避重试; 其他 4xx 快速失败; 遵循 Retry-After。"""

    class FakeResp:
        def __init__(self, obj):
            self.obj = obj

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.obj).encode()

    def _ok(self, obj=None):
        obj = obj or {"succ": 1}
        return self.FakeResp(obj)

    def _err(self, code, headers=None):
        return urllib.error.HTTPError("u", code, "e", headers or {}, io.BytesIO(b""))

    def test_429_then_503_then_success(self):
        responses = [self._err(429), self._err(503), self._ok()]
        sleeps = []
        with (
            mock.patch("urllib.request.urlopen", side_effect=responses),
            mock.patch.object(W.time, "sleep", side_effect=sleeps.append),
        ):
            out = W.http_json("https://x/", hdrs={})
        self.assertEqual(out, {"succ": 1})
        self.assertEqual(len(sleeps), 2)
        self.assertLess(sleeps[0], sleeps[1])  # 指数增长

    def test_retry_after_header_respected(self):
        sleeps = []
        ra = mock.Mock()
        ra.get = mock.Mock(return_value="7")
        with (
            mock.patch("urllib.request.urlopen", side_effect=[self._err(429, ra), self._ok()]),
            mock.patch.object(W.time, "sleep", side_effect=sleeps.append),
        ):
            W.http_json("https://x/", hdrs={})
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 7.0)  # 遵循 Retry-After

    def test_permanent_4xx_fails_fast(self):
        calls = []

        def urlopen(req, timeout=30):
            calls.append(1)
            raise self._err(400)

        with (
            mock.patch("urllib.request.urlopen", side_effect=urlopen),
            mock.patch.object(W.time, "sleep"),
        ):
            with self.assertRaises(urllib.error.HTTPError):
                W.http_json("https://x/", hdrs={})
        self.assertEqual(len(calls), 1)  # 不重试

    def test_transient_exhaustion_raises(self):
        with (
            mock.patch("urllib.request.urlopen", side_effect=[self._err(503)] * 3),
            mock.patch.object(W.time, "sleep"),
        ):
            with self.assertRaises(urllib.error.HTTPError):
                W.http_json("https://x/", hdrs={}, retries=2)


if __name__ == "__main__":
    unittest.main()
