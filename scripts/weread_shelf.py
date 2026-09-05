#!/usr/bin/env python3
"""
weread-shelf-organizer — 微信读书书架自动整理核心脚本

子命令:
  creds                              提取并验证本机微信读书 Mac 客户端凭据
  sync [-o out.json]                 同步书架快照 (书籍/分组/专辑)
  plan  --rules R.json [--baseline B.csv] [--reorganize --source-group "..."] [-o plan.json]
                                     生成整理计划 (自动分类 + 待复核清单)
  apply --plan P.json                批量执行迁移并核验
  review --decisions D.json          应用人工/AI 复核定类并核验
  groups --create NAME | --delete NAME [--purge-empty]
                                     分组管理 (创建 / 删除空分组)
  verify --plan P.json               核验计划中的书是否已落位

原则: 只移动「未分组」的书; 用户放入其他自定义分组的书一律跳过;
      不删除书籍、不改变私密状态; 迁移后必须核验。

依赖: 仅 Python 3 标准库
凭据: 默认从 macOS 微信读书 Mac 客户端日志提取; 也可设环境变量
      WEREAD_VID / WEREAD_SKEY (可选 WEREAD_V) 在任意平台使用。
说明: 通过已登录的微信读书客户端凭据调用其官方接口,
      凭据只驻留内存, 不落盘、不回显。
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

API = "https://i.weread.qq.com"
APP_NAME = os.environ.get("WEREAD_APP_NAME", "微信读书")
LOG_DIR = Path(
    os.environ.get(
        "WEREAD_LOG_DIR", Path.home() / "Library/Containers/com.tencent.weread/Data/Documents/log"
    )
)
BATCH = 40
UA_DEFAULT = "WeRead/10.2.1 (iPad; iOS 26.5; Scale/2.00)"
VER_DEFAULT = "10.2.1.87"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 凭据
def extract_cred():
    """启动 Mac 客户端, 从其本地日志提取 vid/skey(仅驻留内存)。"""
    subprocess.run(["open", "-a", APP_NAME], capture_output=True)
    time.sleep(8)
    logs = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return None
    text = logs[-1].read_text(encoding="utf-8", errors="ignore")
    skeys = re.findall(r'skey\s*=+\s*"([A-Za-z0-9_@!+-]{6,})"', text)
    skeys += re.findall(r"skey\s*=\s*([A-Za-z0-9_@!+-]{6,});", text)
    vids = re.findall(r"vid\s*=+\s*\"?(\d{6,12})\"?", text)
    vers = re.findall(r'[vv]\s*=\s*"?(\d+\.\d+\.\d+(?:\.\d+)?)"?\s*;', text)
    if not skeys or not vids:
        return None
    cred = {
        "vid": Counter(vids).most_common(1)[0][0],
        "skey": Counter(skeys).most_common(1)[0][0],
        "v": Counter(vers).most_common(1)[0][0] if vers else VER_DEFAULT,
        "ua": UA_DEFAULT,
    }
    # 日志里出现过 App 完整 UA 时优先使用
    m = re.search(r"(WeRead/[\d.]+\s*\([^)]*Scale/[\d.]+\))", text)
    if m:
        cred["ua"] = m.group(1)
    return cred


def headers(cred):
    return {
        "vid": cred["vid"],
        "skey": cred["skey"],
        "v": cred["v"],
        "User-Agent": cred["ua"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def http_json(url, payload=None, hdrs=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET", headers=hdrs or {}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _mask(vid):
    """日志中脱敏 vid, 避免录屏/日志泄露个人标识。"""
    return f"{vid[:2]}****{vid[-2:]}" if vid and len(vid) > 4 else "****"


def get_cred(retry=2):
    # 路径 1: 环境变量 (适用于无 Mac 客户端的环境, 如 Linux/CI, 凭据自行提取)
    vid, skey = os.environ.get("WEREAD_VID"), os.environ.get("WEREAD_SKEY")
    if vid and skey:
        cred = {
            "vid": vid,
            "skey": skey,
            "v": os.environ.get("WEREAD_V", VER_DEFAULT),
            "ua": UA_DEFAULT,
        }
        try:
            http_json(
                f"{API}/shelf/sync?userFlag=0&synckey=&teenmode=0&album=1", hdrs=headers(cred)
            )
            log(f"凭据有效 (环境变量, vid={_mask(vid)})")
            return cred
        except urllib.error.HTTPError as e:
            log(f"环境变量凭据无效(HTTP {e.code}), 回退到客户端日志提取")
    # 路径 2: macOS 微信读书客户端日志 (自动启动客户端)
    for attempt in range(retry):
        cred = extract_cred()
        if cred:
            try:
                http_json(
                    f"{API}/shelf/sync?userFlag=0&synckey=&teenmode=0&album=1", hdrs=headers(cred)
                )
                log(f"凭据有效 (vid={_mask(cred['vid'])})")
                return cred
            except urllib.error.HTTPError as e:
                log(f"凭据无效(HTTP {e.code}), 重启客户端刷新登录 ({attempt + 1}/{retry})")
                subprocess.run(["pkill", "-x", "WeRead"], capture_output=True)
                time.sleep(5)
        else:
            log(f"日志中未找到凭据, 等待客户端启动 ({attempt + 1}/{retry})")
            time.sleep(8)
    print(
        "FATAL: 无法获取有效凭据。请打开微信读书 Mac 客户端并确认已登录"
        "(必要时重新扫码), 然后重试。",
        file=sys.stderr,
    )
    sys.exit(2)


# ---------------------------------------------------------------- 书架
def sync_shelf(hdrs):
    return http_json(f"{API}/shelf/sync?userFlag=0&synckey=&teenmode=0&album=1", hdrs=hdrs)


def split_groups(shelf, group_names):
    """按配置的分组名划分: 目标分组 / 用户自定义分组。"""
    aid = {a["name"]: a["archiveId"] for a in shelf.get("archive", [])}
    in_target, in_custom = set(), {}
    for a in shelf.get("archive", []):
        if a["name"] in group_names:
            in_target.update(a.get("bookIds", []))
        elif a["name"] != "归档":
            in_custom[a["name"]] = a.get("bookIds", [])
    return aid, in_target, in_custom


# ---------------------------------------------------------------- 规则
def load_rules(path):
    with open(path, encoding="utf-8") as f:
        r = json.load(f)
    groups = [g["name"] for g in r["groups"]]
    assert len(groups) == len(set(groups)), "分组名重复"
    cat_map = {}
    for cat, g in r.get("category_map", {}).items():
        cat_map[cat.strip()] = g
    conf = r.get("confidence", {})
    return {
        "groups": groups,
        "group_desc": {g["name"]: g.get("description", "") for g in r["groups"]},
        "category_map": cat_map,
        "match_confidence": {
            "full_match": float(conf.get("full_match", 0.95)),
            "head_match": float(conf.get("head_match", 0.75)),
        },
        "min_confidence": float(r.get("min_confidence", 0.6)),
    }


def load_baseline(path):
    """CSV: bookId,target_group"""
    base = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip().isdigit():
                base[row[0].strip()] = row[1].strip()
    return base


def classify(book, rules, stats):
    """平台分类 → (分组名, 依据, 置信度)。

    恒返回 3 元组: 无映射时为 (None, 原因, 0.0)。
    置信度按匹配类型取值(可在规则文件 confidence 节配置):
      full_match=完整分类命中, head_match=主栏目命中。
    """
    cat = str(book.get("category") or "").strip()
    if not cat:
        return None, "无平台分类(多为导入书)", 0.0
    conf = rules["match_confidence"]
    g = rules["category_map"].get(cat)
    if g:
        stats[cat] = stats.get(cat, 0) + 1
        return g, f"平台分类「{cat}」命中映射", conf["full_match"]
    # 模糊: 分类主栏目匹配 (如 "精品小说-悬疑推理" → "精品小说")
    head = cat.split("-")[0].strip()
    g = rules["category_map"].get(head)
    if g:
        stats[cat] = stats.get(cat, 0) + 1
        return g, f"平台分类主栏目「{head}」命中映射", conf["head_match"]
    return None, f"平台分类「{cat}」未配置映射", 0.0


# ---------------------------------------------------------------- 子命令
def cmd_creds(_):
    get_cred()
    log("凭据提取与验证成功")


def cmd_sync(args):
    hdrs = headers(get_cred())
    shelf = sync_shelf(hdrs)
    out = args.output or "shelf_snapshot.json"
    slim = {
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "books": [
            {
                "bookId": b["bookId"],
                "title": b.get("title", ""),
                "author": b.get("author", ""),
                "category": b.get("category", ""),
                "secret": b.get("secret", 0),
                "finishReading": b.get("finishReading", 0),
                "readUpdateTime": b.get("readUpdateTime", 0),
            }
            for b in shelf.get("books", [])
        ],
        "archive": shelf.get("archive", []),
        "albums": len(shelf.get("albums", [])),
        "mp": bool(shelf.get("mp")),
    }
    Path(out).write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"书架快照: {len(slim['books'])} 本电子书, {len(slim['archive'])} 个分组 → {out}")


def cmd_plan(args):
    rules = load_rules(args.rules)
    group_names = set(rules["groups"])
    hdrs = headers(get_cred())
    shelf = sync_shelf(hdrs)
    books = {b["bookId"]: b for b in shelf.get("books", [])}
    aid, in_target, in_custom = split_groups(shelf, group_names)

    # 重组模式: 仅显式白名单里的来源分组允许重新归组, 其他分组一律不动
    source_groups = []
    if args.reorganize:
        source_groups = [s.strip() for s in (args.source_group or "").split(",") if s.strip()]
        for s in [x for x in source_groups if x not in in_custom]:
            log(f"⚠️ 来源分组不存在(或非自定义分组): {s}")
        source_groups = [s for s in source_groups if s in in_custom]
        if not source_groups:
            log("⚠️ --reorganize 未提供有效 --source-group 白名单, 本次仅整理未分组书")
    source_snapshot = {s: sorted(in_custom[s]) for s in source_groups}

    def current_group(bid):
        for a in shelf.get("archive", []):
            if bid in a.get("bookIds", []) and a["name"] != "归档":
                return a["name"]
        return None

    todo = []
    for bid, b in books.items():
        g = current_group(bid)
        if g is None or (args.reorganize and g in source_groups):
            todo.append((b, g))
    n_src = sum(1 for _, g in todo if g is not None)
    log(
        f"待整理: 未分组 {len(todo) - n_src} 本"
        + (f" + 白名单来源分组 {n_src} 本" if args.reorganize else "")
    )

    baseline = load_baseline(args.baseline) if args.baseline else {}
    stats, moves, review = Counter(), [], []
    for b, from_group in todo:
        bid = b["bookId"]
        if bid in baseline:
            g = baseline[bid]
            if g not in group_names:
                log(f"⚠️ 基线分组「{g}」不在规则中, 跳过: {b.get('title', '')[:24]}")
                continue
            moves.append(
                {
                    "bookId": bid,
                    "title": b.get("title", ""),
                    "from": from_group,
                    "to": g,
                    "basis": "基线表格指定",
                    "confidence": 1.0,
                }
            )
        else:
            g, basis, conf = classify(b, rules, stats)
            if g and conf >= rules["min_confidence"]:
                moves.append(
                    {
                        "bookId": bid,
                        "title": b.get("title", ""),
                        "from": from_group,
                        "to": g,
                        "basis": basis,
                        "confidence": conf,
                    }
                )
            else:
                item = {
                    "bookId": bid,
                    "title": b.get("title", ""),
                    "author": b.get("author", ""),
                    "category": b.get("category", ""),
                    "hint": basis,
                    "from": from_group,
                    "confidence": conf,
                }
                if g:  # 有候选但低于阈值: 附带建议供复核参考
                    item["suggest"] = g
                    item["hint"] += f"(候选「{g}」, 置信度 {conf} < 阈值 {rules['min_confidence']})"
                review.append(item)

    plan = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "reorganize" if args.reorganize else "incremental",
        "total_books": len(books),
        "ungrouped": len(todo) - n_src,
        "moves": moves,
        "review": review,
        "skipped_custom_groups": {g: len(ids) for g, ids in in_custom.items()},
        "source_snapshot": source_snapshot,
        "group_archive_ids": {g: aid.get(g) for g in group_names if aid.get(g)},
        "missing_groups": [g for g in group_names if not aid.get(g)],
    }
    out = args.output or "shelf_plan.json"
    Path(out).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    log(
        f"计划: 自动迁移 {len(moves)} 本, 待复核 {len(review)} 本, "
        f"跳过自定义分组 {sum(len(v) for v in in_custom.values())} 本 → {out}"
    )
    if plan["missing_groups"]:
        log(f"⚠️ 以下分组不存在, apply 前需创建: {plan['missing_groups']}")
    if args.dry_run:
        for m in moves[:15]:
            log(f"  → {m['to']}: {m['title'][:28]}")
        if len(moves) > 15:
            log(f"  ... 共 {len(moves)} 本")


def _move_batch(hdrs, ids, gid, gname):
    for attempt in range(3):
        try:
            resp = http_json(
                f"{API}/shelf/archive",
                {"bookIds": ids, "albumIds": [], "archiveId": gid, "name": gname},
                hdrs,
            )
            if resp.get("succ") == 1:
                return True
            log(f"  ⚠️ 异常响应 {resp}, 重试 {attempt + 1}/3")
            time.sleep(2)
        except urllib.error.HTTPError as e:
            body = e.read()[:120]
            log(f"  ⚠️ HTTP {e.code}: {body}, 重试 {attempt + 1}/3")
            if e.code == 401:
                print("FATAL: 凭据失效, 重新运行以刷新", file=sys.stderr)
                sys.exit(2)
            time.sleep(2 + attempt * 2)
        except Exception as e:
            log(f"  ⚠️ {e}, 重试 {attempt + 1}/3")
            time.sleep(2)
    return False


def _do_moves(hdrs, by_group, aid):
    moved, failed = [], []
    for g, ids in sorted(by_group.items()):
        gid = aid.get(g)
        if not gid:
            log(f"❌ 分组不存在: {g} ({len(ids)} 本未移动), 先用 groups --create 创建")
            failed.extend(ids)
            continue
        for i in range(0, len(ids), BATCH):
            chunk = ids[i : i + BATCH]
            if _move_batch(hdrs, chunk, gid, g):
                moved.extend(chunk)
                log(f"{g} +{len(chunk)} (累计 {len(moved)})")
            else:
                failed.extend(chunk)
                log(f"  ❌ 批次失败 {len(chunk)} 本")
            time.sleep(0.4)
    return moved, failed


def _verify(hdrs, expected):
    """核验每本书落在「预期分组」(而非任意目标分组)。

    expected: {bookId: 分组名}; 返回错位清单 [(bookId, 期望分组, 实际分组)]。
    """
    time.sleep(2)
    shelf = sync_shelf(hdrs)
    actual = {}
    for a in shelf.get("archive", []):
        for bid in a.get("bookIds", []):
            actual[bid] = a["name"]
    return [(b, g, actual.get(b)) for b, g in expected.items() if actual.get(b) != g]


def snapshot_current(shelf):
    """书架 → {bookId: 当前分组名}(未分组不出现在映射中)。

    系统分组「归档」(archiveId=1) 是客户端对未分组书的承载容器, 视同未分组。
    """
    actual = {}
    for a in shelf.get("archive", []):
        if a["name"] == "归档":
            continue
        for bid in a.get("bookIds", []):
            actual[bid] = a["name"]
    return actual


def plan_age_hours(plan):
    try:
        return (time.time() - datetime.fromisoformat(plan["generated_at"]).timestamp()) / 3600
    except Exception:
        return 0.0


def _write_json_report(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"结构化报告 → {path}")


def cmd_apply(args):
    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    hdrs = headers(get_cred())
    if args.dry_run:
        log(f"[DRY-RUN] 将迁移 {len(plan['moves'])} 本")
        return
    if plan_age_hours(plan) > 24:
        log("⚠️ 计划已生成超过 24 小时, 建议重新 plan 以获取最新书架状态")
    # 执行前重新同步, 逐本校验「当前分组 == 计划记录的来源」——
    # 防止计划过期或被篡改后绕过「只动未分组/白名单分组」的安全线
    shelf = sync_shelf(hdrs)
    aid = {a["name"]: a["archiveId"] for a in shelf.get("archive", [])}
    actual = snapshot_current(shelf)
    valid, stale = [], []
    for m in plan["moves"]:
        now = actual.get(m["bookId"])
        if now != m.get("from"):
            stale.append((m, now))
        else:
            valid.append(m)
    for m, now in stale[:10]:
        log(
            f"  ⏭️ 状态已变, 跳过: {m.get('title', '')[:20]} | "
            f"计划来源={m.get('from') or '未分组'} → 当前={now or '未分组'}"
        )
    if stale:
        log(f"共 {len(stale)} 条计划因书架状态变化被跳过")
    group_sourced = [m for m in valid if m.get("from")]
    if group_sourced and not args.yes:
        log(
            f"⚠️ 计划含 {len(group_sourced)} 本来自已有分组的书(重组迁移)。"
            f"请人工复核 plan.json 后加 --yes 执行。"
        )
        sys.exit(3)
    by_group = {}
    for m in valid:
        by_group.setdefault(m["to"], []).append(m["bookId"])
    moved, failed = _do_moves(hdrs, by_group, aid)
    expected = {m["bookId"]: m["to"] for m in valid}
    wrong = _verify(hdrs, {b: expected[b] for b in moved})
    log(
        f"迁移完成: 成功 {len(moved)} 本, 失败 {len(failed)} 本, "
        f"跳过状态不符 {len(stale)} 本, 核验错位 {len(wrong)} 本"
    )
    for b, want, got in wrong[:10]:
        log(f"  ⚠️ {b[:8]} 期望「{want}」实际「{got}」")
    if args.json_report:
        _write_json_report(
            args.json_report,
            {
                "command": "apply",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "planned": len(plan["moves"]),
                "moved": sorted(moved),
                "failed": sorted(failed),
                "stale": [
                    {"bookId": m["bookId"], "planned_from": m.get("from"), "actual_group": now}
                    for m, now in stale
                ],
                "wrong": [{"bookId": b, "expected": w, "actual": g} for b, w, g in wrong],
            },
        )
    if failed or wrong:
        log("❌ 存在失败或核验错位, 以非零退出码结束 (细节见上方日志/报告)")
        sys.exit(1)


def cmd_review(args):
    with open(args.decisions, encoding="utf-8") as f:
        decisions = json.load(f)
    hdrs = headers(get_cred())
    shelf = sync_shelf(hdrs)
    aid = {a["name"]: a["archiveId"] for a in shelf.get("archive", [])}
    actual = snapshot_current(shelf)
    # 状态校验: 决定可携带 from(来源分组, 缺省视为未分组), 当前状态不符则跳过
    kept, skipped = [], 0
    for d in decisions:
        exp = d.get("from")
        now = actual.get(str(d["bookId"]))
        if now != exp:
            skipped += 1
            log(
                f"  ⏭️ 状态不符, 跳过: {d.get('title') or d['bookId']} | "
                f"预期来源={exp or '未分组'} → 当前={now or '未分组'}"
            )
            continue
        kept.append(d)
    if skipped:
        log(f"共 {skipped} 条复核决定因状态不符被跳过")
    by_group = {}
    for d in kept:
        g = d["group"]
        if g not in aid:
            log(f"❌ 未知分组「{g}」, 跳过 {d.get('bookId')}")
            continue
        by_group.setdefault(g, []).append(str(d["bookId"]))
    moved, failed = _do_moves(hdrs, by_group, aid)
    expected = {str(d["bookId"]): d["group"] for d in kept}
    wrong = _verify(hdrs, {b: expected[b] for b in moved})
    log(
        f"复核应用完成: 移动 {len(moved)} 本, 失败 {len(failed)}, "
        f"跳过状态不符 {skipped}, 核验错位 {len(wrong)}"
    )
    for b, want, got in wrong[:10]:
        log(f"  ⚠️ {b[:8]} 期望「{want}」实际「{got}」")
    if args.json_report:
        _write_json_report(
            args.json_report,
            {
                "command": "review",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "planned": len(decisions),
                "moved": sorted(moved),
                "failed": sorted(failed),
                "stale": skipped,
                "wrong": [{"bookId": b, "expected": w, "actual": g} for b, w, g in wrong],
            },
        )
    if failed or wrong:
        log("❌ 存在失败或核验错位, 以非零退出码结束 (细节见上方日志/报告)")
        sys.exit(1)


def cmd_groups(args):
    hdrs = headers(get_cred())
    shelf = sync_shelf(hdrs)
    archives = {a["name"]: a for a in shelf.get("archive", [])}
    if args.create:
        name = args.create
        if name in archives:
            log(f"分组已存在: {name} ({len(archives[name].get('bookIds', []))} 本)")
            return
        resp = http_json(
            f"{API}/shelf/archive",
            {"bookIds": [], "albumIds": [], "archiveId": 0, "name": name},
            hdrs,
        )
        log(f"创建分组「{name}」: {resp}")
    elif args.delete:
        a = archives.get(args.delete)
        if not a:
            log(f"分组不存在: {args.delete}")
            return
        ids = a.get("bookIds", [])
        if ids and not args.force:
            log(
                f"⚠️ 分组「{args.delete}」还有 {len(ids)} 本书, "
                f"如确认要连同分组删除请加 --force (书不会被移出书架, 只解除分组)"
            )
            return
        resp = http_json(
            f"{API}/shelf/deleteArchive", {"archiveId": a["archiveId"], "removeBooks": 0}, hdrs
        )
        log(f"删除分组「{args.delete}」: {resp} (书籍保留在书架)")
    elif args.purge_empty:
        n = 0
        for name, a in sorted(archives.items()):
            if name != "归档" and not a.get("bookIds"):
                resp = http_json(
                    f"{API}/shelf/deleteArchive",
                    {"archiveId": a["archiveId"], "removeBooks": 0},
                    hdrs,
                )
                log(f"🗑️ 删除空分组: {name} => {resp}")
                n += 1
                time.sleep(0.4)
        log(f"共清理 {n} 个空分组")
    else:
        for name, a in sorted(archives.items()):
            print(f"  {name}: {len(a.get('bookIds', []))} 本 (archiveId={a['archiveId']})")


def cmd_verify(args):
    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    hdrs = headers(get_cred())
    expected = {m["bookId"]: m["to"] for m in plan["moves"]}
    wrong = _verify(hdrs, expected)
    if wrong:
        for b, want, got in wrong[:10]:
            log(f"  ❌ {b[:8]} 期望「{want}」实际「{got}」")
        log(f"❌ {len(wrong)} 本未落位/错位")
        sys.exit(1)
    log(f"✅ 全部落位到预期分组 ({len(expected)} 本)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="只看计划不执行")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("creds", help="提取并验证凭据")

    p = sub.add_parser("sync", help="同步书架快照")
    p.add_argument("-o", "--output", default="shelf_snapshot.json")

    p = sub.add_parser("plan", parents=[common], help="生成整理计划")
    p.add_argument("--rules", required=True, help="分组与分类映射规则 JSON")
    p.add_argument("--baseline", help="基线 CSV (bookId,target_group)")
    p.add_argument(
        "--reorganize",
        action="store_true",
        help="重组模式: 允许迁移 --source-group 白名单分组内的书",
    )
    p.add_argument(
        "--source-group", default="", help='重组来源分组白名单, 逗号分隔, 如 "旧榜单A,旧榜单B"'
    )
    p.add_argument("-o", "--output", default="shelf_plan.json")

    p = sub.add_parser("apply", parents=[common], help="执行计划迁移")
    p.add_argument("--plan", required=True)
    p.add_argument("--yes", action="store_true", help="确认执行含「来自已有分组」书籍的重组迁移")
    p.add_argument("--json-report", help="写入结构化结果 JSON (moved/failed/stale/wrong)")

    p = sub.add_parser("review", help="应用复核定类")
    p.add_argument(
        "--decisions", required=True, help='JSON: [{"bookId":"..","group":"..","from":null}]'
    )
    p.add_argument("--json-report", help="写入结构化结果 JSON (moved/failed/stale/wrong)")

    p = sub.add_parser("groups", help="分组管理")
    p.add_argument("--create", help="创建分组")
    p.add_argument("--delete", help="删除分组(默认仅空分组)")
    p.add_argument("--force", action="store_true", help="允许删除非空分组(书保留在书架)")
    p.add_argument("--purge-empty", action="store_true", help="清理所有空分组")
    p.add_argument("--list", action="store_true", help="列出全部分组")

    p = sub.add_parser("verify", help="核验计划落位")
    p.add_argument("--plan", required=True)

    args = ap.parse_args()
    {
        "creds": cmd_creds,
        "sync": cmd_sync,
        "plan": cmd_plan,
        "apply": cmd_apply,
        "review": cmd_review,
        "groups": cmd_groups,
        "verify": cmd_verify,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
