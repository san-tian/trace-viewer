#!/usr/bin/env python3
"""build_viewer.py —— 把「采样记录 + 判分记录」编译成可离线浏览的查看器。

产出结构
--------
out/
  index.html          查看器本体（从 viewer/index.html 拷来）
  index.js            分数索引（首屏加载）
  cells/<tag>_<row>.js  每个「源 × 题」的明细，点开才加载

输入结构（约定，可用 --raw/--judged 改根目录）
---------------------------------------------
raw/<tag>/rowNNNN.sK.json        采样记录（见 docs/DATA-FORMAT.md）
judged/<tag>/judged/rowNNNN.sK.json  判分记录

用法
----
python3 build_viewer.py --raw ./raw --judged ./judged --out ./site \
    --title "My Benchmark" --config ./config.json

config.json（可选）
------------------
{
  "title": "My Benchmark",
  "subtitle": "60 题 × 6 采样 × 4 源",
  "solved_fraction": 0.7,
  "min_pass": 6,
  "subjects": {"biology": "生物", "chemistry": "化学", "physics": "物理"},
  "sources": [{"tag": "1-vllm", "name": "vLLM"}, ...],   # 缺省则自动从 raw/ 的目录名推断
  "reference": {"name": "官方 API", "p1": 0.2611, "mean": 4.7617},  # 可选对照行
  "downloads": [{"label": "分数总表 CSV", "path": "download/scores.csv"}, ...]
}
"""
from __future__ import annotations
import argparse, json, math, os, re, shutil, statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOLVED = 0.7


def rtok(u: dict) -> int:
    """推理（思考）token 数：有的源在 completion_tokens_details，有的在顶层。"""
    return ((u.get("completion_tokens_details") or {}).get("reasoning_tokens")
            or u.get("reasoning_tokens") or 0)


def js_safe(s: str) -> str:
    """防止内容里的 </script> / <!-- 破坏 <script> 块。"""
    return s.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def dump(o) -> str:
    return js_safe(json.dumps(o, ensure_ascii=False, separators=(",", ":")))


def discover_tags(raw: Path, judged: Path, cfg: dict) -> list[tuple[str, str]]:
    if cfg.get("sources"):
        return [(s["tag"], s.get("name", s["tag"])) for s in cfg["sources"]]
    tags = sorted(d.name for d in raw.iterdir() if d.is_dir() and not d.name.startswith("_"))
    out = []
    for t in tags:
        if not (judged / t).exists():
            continue
        out.append((t, t))
    return out


def load(raw: Path, judged: Path, tags):
    data, qmeta = {}, {}
    for tag, _ in tags:
        for f in sorted((raw / tag).glob("row*.json")):
            r = json.load(open(f, encoding="utf-8"))
            data[(tag, r["row_index"], r["s_idx"])] = {"raw": r, "judged": None}
            qmeta[r["row_index"]] = {"subject": r.get("subject", "?"),
                                     "q": r.get("question", ""), "gold": r.get("gold", "")}
    for tag, _ in tags:
        jd = judged / tag / "judged"
        if not jd.exists():
            jd = judged / tag
        for f in sorted(jd.glob("row*.json")):
            j = json.load(open(f, encoding="utf-8"))
            k = (tag, j["row_index"], j["s_idx"])
            if k in data:
                data[k]["judged"] = j
    return data, qmeta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--judged", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config")
    ap.add_argument("--title")
    ap.add_argument("--samples", type=int, default=0, help="每题采样数（0=自动从文件名推断）")
    ap.add_argument("--scores-csv", action="store_true", help="额外输出 download/scores.csv")
    args = ap.parse_args()

    cfg = {}
    if args.config and Path(args.config).exists():
        cfg = json.load(open(args.config, encoding="utf-8"))
    if args.title:
        cfg["title"] = args.title

    raw, judged, out = Path(args.raw), Path(args.judged), Path(args.out)
    solved = float(cfg.get("solved_fraction", SOLVED))
    subj_cn = cfg.get("subjects") or {}
    out.mkdir(parents=True, exist_ok=True)
    (out / "cells").mkdir(exist_ok=True)

    tags = discover_tags(raw, judged, cfg)
    if not tags:
        raise SystemExit("没找到任何源（raw/ 下需要有以源命名的目录）")
    data, qmeta = load(raw, judged, tags)
    print(f"载入 {len(data)} 条样本，{len(qmeta)} 道题，{len(tags)} 个源")

    # 每题采样数
    ns = args.samples
    if not ns:
        ns = max(s for (_, _, s) in data.keys()) + 1

    # ── 索引 ──
    cells = {}
    for (tag, row, si), v in data.items():
        j, r = v["judged"] or {}, v["raw"]
        c = cells.setdefault(f"{tag}|{row}", {"tag": tag, "row": row,
                                              "subject": r.get("subject", "?"),
                                              "s": [None] * ns})
        c["s"][si] = {
            "rw": j.get("reward"), "pt": j.get("points_median"), "vt": j.get("votes"),
            "sk": bool(j.get("skipped")), "fr": r.get("finish_reason"),
            "ct": (r.get("usage") or {}).get("completion_tokens"),
            "el": r.get("elapsed_s"), "at": r.get("attempts"),
        }
    for c in cells.values():
        ss = [x for x in c["s"] if x]
        valid = [x for x in ss if x["rw"] is not None]
        c["nsolved"] = sum(1 for x in valid if x["rw"] >= solved)
        c["nvalid"] = len(valid)
        c["nskip"] = sum(1 for x in ss if x["sk"])
        c["mean"] = round(st.mean([x["pt"] for x in valid if x["pt"] is not None]), 3) if valid else None
        n, k = c["nvalid"], min(c["nvalid"], ns)
        if n == 0:
            c["pk"] = None
        elif n - c["nsolved"] < k:
            c["pk"] = 1.0
        else:
            c["pk"] = 1.0 - math.comb(n - c["nsolved"], k) / math.comb(n, k)

    rows = sorted({c["row"] for c in cells.values()})
    rowdiff = {}
    for r in rows:
        cs = [c for c in cells.values() if c["row"] == r]
        n = sum(c["nvalid"] for c in cs)
        rowdiff[r] = round(sum(c["nsolved"] for c in cs) / n, 4) if n else None

    summary = {}
    for tag, name in tags:
        cs = [c for c in cells.values() if c["tag"] == tag]
        ss = [x for c in cs for x in c["s"] if x]
        valid = [x for x in ss if x["rw"] is not None]
        p1s, pks = [], []
        for c in cs:
            v = [x for x in c["s"] if x and x["rw"] is not None]
            if not v:
                continue
            p1s.append(sum(1 for x in v if x["rw"] >= solved) / len(v))
            if c["pk"] is not None:
                pks.append(c["pk"])
        summary[tag] = {
            "name": name, "n": len(ss),
            "p1": round(st.mean(p1s), 4) if p1s else 0,
            "pk": round(st.mean(pks), 4) if pks else 0,
            "mean": round(st.mean([x["pt"] for x in valid if x["pt"] is not None]), 4) if valid else 0,
            "skip": sum(1 for x in ss if x["sk"]),
        }

    (out / "index.js").write_text("window.FSR=" + dump({
        "tags": [t for t, _ in tags], "names": {t: n for t, n in tags},
        "subj": subj_cn, "summary": summary, "rowdiff": rowdiff,
        "title": cfg.get("title", "Trace Viewer"),
        "subtitle": cfg.get("subtitle", ""),
        "passLabel": cfg.get("pass_label", f"pass@{ns}"),
        "minPass": ns, "solvedFraction": solved,
        "reference": cfg.get("reference"),
        "downloads": cfg.get("downloads", []),
        "qmeta": {str(r): {"subject": qmeta[r]["subject"]} for r in qmeta},
        "cells": list(cells.values()),
    }) + ";", encoding="utf-8")
    print(f"index.js  {os.path.getsize(out/'index.js')/1e3:.0f} KB")

    # ── 每个单元格的明细 ──
    n_cell = 0
    for tag, _ in tags:
        for row in rows:
            samples = []
            for si in range(ns):
                v = data.get((tag, row, si))
                if not v:
                    continue
                r, j = v["raw"], v["judged"] or {}
                u = r.get("usage") or {}
                votes = []
                for vt in (j.get("votes_detail") or []):
                    vu = vt.get("usage") or {}
                    vrt = ((vu.get("completion_tokens_details") or {}).get("reasoning_tokens")
                           or vu.get("reasoning_tokens") or 0)
                    vct = vu.get("completion_tokens") or 0
                    votes.append({
                        "pt": vt.get("points"), "fr": vt.get("fraction"), "vd": vt.get("verdict"),
                        "said": vt.get("content") or "", "why": vt.get("reasoning_content") or "",
                        "ext": vt.get("extract_content") or "", "dur": vt.get("duration_s"),
                        "eff": vt.get("reasoning_effort"), "mdl": vt.get("model"),
                        "utok": vct, "wtok": vrt, "stok": max(0, vct - vrt),
                    })
                samples.append({
                    "s": si,
                    "rw": j.get("reward"), "pt": j.get("points_median"),
                    "vt": j.get("votes"), "sk": bool(j.get("skipped")),
                    "fr": r.get("finish_reason"), "ct": u.get("completion_tokens"),
                    "el": r.get("elapsed_s"), "at": r.get("attempts"), "err": r.get("error"),
                    "ans": r.get("answer_visible") or "",
                    "think": r.get("thinking_text") or "",
                    "ptok": u.get("prompt_tokens"), "ttok": rtok(u),
                    "atok": max(0, (u.get("completion_tokens") or 0) - rtok(u)),
                    "votes": votes,
                })
            payload = {"tag": tag, "row": row, "subject": qmeta[row]["subject"],
                       "q": qmeta[row]["q"], "gold": qmeta[row]["gold"], "samples": samples}
            gname = f"{tag.replace('-','_')}_{row}"
            (out / "cells" / f"{tag}_{row:04d}.js").write_text(
                f"window.FSRC_{gname}=" + dump(payload) + ";", encoding="utf-8")
            n_cell += 1
    sz = sum(f.stat().st_size for f in (out / "cells").glob("*.js"))
    print(f"{n_cell} 个单元格，合计 {sz/1e6:.0f} MB")

    # 前端
    import hashlib, re as _re, time as _time
    vhash = hashlib.sha1((str(_time.time()) + str(len(cells))).encode()).hexdigest()[:10]
    html = (HERE / "index.html").read_text(encoding="utf-8")
    # 版本号破缓存：index.js 与 cells/*.js 的 src 都带上 ?v=<hash>。
    # 否则任何中间缓存（浏览器/代理）都可能送旧文件 —— 字段对不上就直接空白。
    html = _re.sub(r'(<script\s+src="index\.js)(")', rf'\1?v={vhash}\2', html)
    html = html.replace("`cells/${tag}_${String(row).padStart(4,'0')}.js`",
                        f"`cells/${{tag}}_${{String(row).padStart(4,'0')}}.js?v={vhash}`")
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"index.html 已就位 (version={vhash}) -> {out}")
    if args.scores_csv:
        import csv
        (out / "download").mkdir(exist_ok=True)
        rows_csv = []
        for (tag, row, si), v in sorted(data.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
            j, r = v["judged"] or {}, v["raw"]
            rows_csv.append({
                "source": dict(tags).get(tag, tag), "subject": r.get("subject"),
                "row": row, "sample": si,
                "reward": j.get("reward"), "points_median": j.get("points_median"),
                "votes": j.get("votes"), "skipped": j.get("skipped"),
                "finish_reason": r.get("finish_reason"),
                "completion_tokens": (r.get("usage") or {}).get("completion_tokens"),
                "elapsed_s": r.get("elapsed_s"), "attempts": r.get("attempts"),
            })
        with open(out / "download" / "scores.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows_csv[0].keys()))
            w.writeheader(); w.writerows(rows_csv)
        print(f"download/scores.csv  {len(rows_csv)} 行")


if __name__ == "__main__":
    main()
