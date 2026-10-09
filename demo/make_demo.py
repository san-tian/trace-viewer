#!/usr/bin/env python3
"""生成一套**合成**演示数据，用来试跑查看器（不含任何真实基准内容）。

产出符合 docs/DATA-FORMAT.md 的 raw/ 与 judged/ 结构：
  demo/raw/<source>/rowNNNN.sK.json
  demo/judged/<source>/judged/rowNNNN.sK.json

用法: python3 make_demo.py [输出目录，默认 ./demo]
"""
from __future__ import annotations
import json, random, sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo")

SOURCES = [("alpha", "Alpha-7B"), ("beta", "Beta-MoE"), ("gamma", "Gamma-API")]
SUBJECTS = ["algebra", "geometry", "combinatorics"]
N_Q, N_S = 12, 4          # 12 题 × 4 采样

# 各源「能力水平」：越高越常答对
SKILL = {"alpha": 0.72, "beta": 0.55, "gamma": 0.40}

WORDS = ("consider the invariant derive the bound apply induction reduce to a known case "
         "check the boundary enumerate small cases look for a bijection use generating functions "
         "verify numerically then prove the direction is forced by symmetry").split()


def blob(rng, n_words):
    return " ".join(rng.choice(WORDS) for _ in range(n_words))


def main():
    rng = random.Random(20261009)
    for tag, _ in SOURCES:
        (OUT / "raw" / tag).mkdir(parents=True, exist_ok=True)
        (OUT / "judged" / tag / "judged").mkdir(parents=True, exist_ok=True)

    for q in range(N_Q):
        subject = SUBJECTS[q % len(SUBJECTS)]
        question = (f"Problem {q+1} ({subject}). [SYNTHETIC DEMO] " + blob(rng, 40) + "?")
        gold = "Points: 2.0, Item: correct setup\nPoints: 1.5, Item: correct final answer"

        for tag, sname in SOURCES:
            for s in range(N_S):
                skill = SKILL[tag]
                # 10% 概率模拟「思考没闭合」→ skip_empty
                skip = rng.random() < 0.10
                if skip:
                    think = blob(rng, 900) + " and then I should probably"
                    ans, fr = "", "length"
                    judged = {"reward": 0.0, "votes": "skip-empty",
                              "points_median": 0.0, "skipped": True,
                              "subject": subject, "row_index": q, "s_idx": s,
                              "completion_tokens": 131072, "finish_reason": "length",
                              "judge_elapsed_s": 0.0, "votes_detail": []}
                    ct, rt = 131072, 129000
                else:
                    good = rng.random() < skill
                    n_items = 4
                    hits = n_items if good else rng.randint(0, 2)
                    think = ("We need answer. " + blob(rng, rng.randint(120, 600)) +
                             "\n\nLet me write the final answer now.")
                    ans = ("# Solution\n\n" + blob(rng, rng.randint(60, 260)) +
                           f"\n\nTherefore the answer is **{rng.randint(2,97)}**.")
                    fr = "stop" if rng.random() > 0.12 else "length"
                    votes, pts = [], []
                    for v in range(3):
                        p = round(hits / n_items * 10, 2) + rng.choice([0, 0, 0, 0.5, -0.5])
                        p = max(0.0, min(10.0, p))
                        pts.append(p)
                        votes.append({
                            "points": p, "fraction": round(p / 10, 4),
                            "verdict": "C" if p / 10 >= 0.7 else "I",
                            "content": (f"Rubric item-by-item grading:\n\n"
                                        f"1. **Correct setup (2.0 pts): {2.0 if hits>=1 else 0}/2.0**\n"
                                        f"   - {(blob(rng,18))}: {'present' if hits>=1 else 'missing'}.\n"
                                        f"2. **Correct final answer (1.5 pts): {1.5 if hits>=3 else 0}/1.5**\n"
                                        f"   - {(blob(rng,18))}: {'present' if hits>=3 else 'not shown'}."),
                            "reasoning_content": "We need grading. " + blob(rng, rng.randint(150, 400)),
                            "extract_content": str(p),
                            "duration_s": round(rng.uniform(30, 160), 1),
                            "reasoning_effort": "high", "model": "demo-judge",
                            "usage": {"completion_tokens": rng.randint(4000, 12000),
                                      "prompt_tokens": rng.randint(1500, 4000),
                                      "completion_tokens_details": {
                                          "reasoning_tokens": rng.randint(3000, 9000)}},
                        })
                    med = sorted(pts)[1]
                    judged = {"reward": round(med / 10, 4), "votes": "".join(x["verdict"] for x in votes),
                              "points_median": med, "skipped": False,
                              "subject": subject, "row_index": q, "s_idx": s,
                              "completion_tokens": rng.randint(30000, 120000),
                              "finish_reason": fr,
                              "judge_elapsed_s": round(rng.uniform(60, 300), 1),
                              "votes_detail": votes}
                    ct = judged["completion_tokens"]
                    rt = int(ct * 0.9)

                raw = {
                    "source": tag, "model": sname, "row_index": q, "s_idx": s,
                    "subject": subject, "question": question, "gold": gold,
                    "request_sampling": {"temperature": 1.0, "top_p": 1.0, "max_tokens": 131072},
                    "max_tokens": 131072, "seed": None,
                    "answer_text": ans, "thinking_text": think, "answer_visible": ans or None,
                    "finish_reason": fr,
                    "usage": {"prompt_tokens": 1200, "completion_tokens": ct,
                              "total_tokens": 1200 + ct,
                              "completion_tokens_details": {"reasoning_tokens": rt}},
                    "http_status": 200, "error": None,
                    "elapsed_s": round(rng.uniform(30, 900), 1),
                    "attempts": rng.choice([1, 1, 1, 2]), "failed": False,
                    "skip_empty": not ans, "ts": "2026-01-01T00:00:00Z",
                }
                (OUT / "raw" / tag / f"row{q:04d}.s{s}.json").write_text(
                    json.dumps(raw, ensure_ascii=False), encoding="utf-8")
                (OUT / "judged" / tag / "judged" / f"row{q:04d}.s{s}.json").write_text(
                    json.dumps(judged, ensure_ascii=False), encoding="utf-8")

    n = len(list((OUT / "raw").rglob("*.json")))
    print(f"已生成 {n} 条合成样本 -> {OUT}")


if __name__ == "__main__":
    main()
