# Trace Viewer

**把「大模型采样记录 + LLM 判分记录」编译成一个可离线浏览的网页，用来逐题定位哪个源答得差、差在哪一步。**

单文件前端，零依赖，`file://` 直接打开就能用。

```
┌──────────────────────────────────────────────────────────────────────┐
│  源           pass@1    pass@4   mean pts   skip_empty   条数         │
│  Alpha-7B     0.6250    0.8333     6.5625          1       48         │
│  Beta-MoE     0.4375    0.5833     4.8958          2       48         │
│  Gamma-API    0.3542    0.4167     3.9792          4       48         │
│                                                                      │
│        Alpha    Beta    Gamma     ← 点列头只高亮某源                   │
│  Q01   4/4      2/4     1/4                                          │
│  Q02   3/4      4/4     0/4       ← 颜色 0/4 深红 → 4/4 深绿          │
│  Q03   0/4      0/4     0/4                                          │
│  ...                                                                 │
└──────────────────────────────────────────────────────────────────────┘
                    ↓ 点任意格子
┌──────────────────────────────────────────────────────────────────────┐
│ [源名] [学科] 第 N 题        解出 x/4 · 均分 y · skip z                │
│                                                                      │
│ 📥 输入（人提供的）                                                    │
│   📋 题目原文              prompt                                     │
│   🎯 官方评分标准 gold      rubric      ← judge 逐条对照的依据          │
│                                                                      │
│ 📤 各次采样 s0~s3，每张卡：                                             │
│   🧠 模型思考过程          reasoning_content                          │
│   ✍️ 模型最终回答          answer_visible  ← ★ judge 实际打分的就是这个 │
│   ⚖️ JUDGE 判据（三票）                                                │
│      📄 judge 评分原文      content        ← ★ 逐条 rubric 打分        │
│      🤔 judge 推理过程      reasoning_content                          │
└──────────────────────────────────────────────────────────────────────┘
```

每块都标了**原始 JSON 字段名**和**字符数 · token 数**双口径，方便跟数据文件逐一对照。

---

## 在线演示

**<https://san-tian.github.io/trace-viewer/>** —— 直接用合成数据跑起来的例子。

## 快速开始

```bash
git clone <this-repo> && cd trace-viewer

# ① 看内置演示（合成数据，不是真实基准）
python3 viewer/serve.py 8000 docs
# 打开 http://localhost:8000
# 也可以直接双击 docs/index.html

# ② 换成你自己的数据
cd viewer
python3 build_viewer.py --raw /path/to/raw --judged /path/to/judged \
    --out /path/to/site --config my-config.json --scores-csv
```

> **为什么推荐起个 http.server**：`cells/` 是点开才加载的。
> 直接双击 `index.html` 也能用（数据用 `<script>` 注入而非 `fetch`，绕开 `file://` 的 CORS 限制），
> 但起服务后加载更快、也支持 gzip。
> `viewer/serve.py` 是个增强版（Range 断点续传 + gzip + 缓存头）：
> ```bash
> python3 viewer/serve.py 8000 /path/to/site
> ```

---

## 输入数据格式

两个目录，文件名约定为 `row<题号4位>.s<采样号>.json`：

```
raw/<source>/rowNNNN.sK.json            采样记录
judged/<source>/judged/rowNNNN.sK.json  判分记录
```

`<source>` 是源的短标签（如 `openai`、`local-vllm`），`row0007.s3.json` 表示第 7 题第 4 次采样。

**最小可用的采样记录**：

```jsonc
{
  "row_index": 7, "s_idx": 3, "subject": "algebra",
  "question": "题面……",                 // 要展示的题目
  "gold": "评分标准……",                 // 可选，judge 的依据
  "thinking_text": "模型思考……",        // 可选
  "answer_text": "模型回答……",          // 可选
  "answer_visible": "最终答案……",       // judge 实际打分对象
  "finish_reason": "stop",              // stop / length / null
  "usage": {"prompt_tokens": 1200, "completion_tokens": 45000,
            "completion_tokens_details": {"reasoning_tokens": 40000}},
  "elapsed_s": 312.5, "attempts": 1, "error": null
}
```

**最小可用的判分记录**：

```jsonc
{
  "row_index": 7, "s_idx": 3,
  "reward": 0.75,            // 最终分 0~1（三票 points 中位数 / 10 之类，你自己定义）
  "points_median": 7.5,      // 中位 points（满分 10）
  "votes": "CCI",            // 每票一个字母：C=解出，I=未解出
  "skipped": false,          // true = 空答案短路（未调用 judge），按 0 分计
  "votes_detail": [
    { "points": 7.5, "fraction": 0.75, "verdict": "C",
      "content": "judge 的评分原文（逐条 rubric 打分）",
      "reasoning_content": "judge 的推理过程",
      "extract_content": "7.5",
      "duration_s": 93.2, "model": "gpt-x",
      "usage": {"completion_tokens": 20000,
                "completion_tokens_details": {"reasoning_tokens": 18000}} }
  ]
}
```

字段全部**可选**，缺了就不显示那一块。完整字段与推导关系见 [`docs/data-format.md`](docs/data-format.md)。

---

## 配置

`build_viewer.py --config config.json`：

```jsonc
{
  "title": "My Benchmark",
  "subtitle": "60 题 × 6 采样 × 4 源",
  "solved_fraction": 0.7,        // reward ≥ 此值记「解出」
  "pass_label": "pass@6",        // 表头显示名
  "subjects": {"algebra": "代数", "geometry": "几何"},   // 学科中文化
  "sources": [                    // 不写则自动从 raw/ 目录名推断
    {"tag": "a", "name": "Model A"},
    {"tag": "b", "name": "Model B"}
  ],
  "reference": {"name": "论文报告值", "p1": 0.2611, "mean": 4.7617},  // 可选对照行
  "downloads": [                  // 可选，页面右上角下载下拉
    {"label": "分数总表 CSV", "path": "download/scores.csv", "size": "0.1 MB"}
  ]
}
```

---

## 三个筛子快速定位薄弱点

| 控件 | 作用 |
|---|---|
| **排序 →「题目难度（最难在前）」** | 所有源都吃力的题排最前 |
| **「只显示解出 ≤ N 次的格子」** | 设成 0/1 → 答得好的自动变暗，只留薄弱点 |
| **「只看所有源都答不好的题」** | 平均解出率低于阈值的题 |
| 点汇总表某行 / 列头 | 只高亮某个源 |

---

## 几个设计取舍

**为什么用 `<script>` 注入而不是 `fetch()`**
`file://` 下 `fetch()` 会被 CORS 拦，`<script src>` 不会 —— 所以双击 HTML 就能用，不必起服务器。

**为什么拆成「索引 + 每格一个文件」**
完整数据可能几百 MB。`index.js` 只装分数（几十 KB，首屏秒开），
每个「源 × 题」一格单独一个文件（点开才加载）。

**为什么内容里要转义 `</script>`**
模型自由输出的文本里可能出现任意字符。数据生成时会转义 `</script` 与 `<!--`，避免撑破页面。

**为什么大段文本用 `textContent` 而不是 `innerHTML`**
思考/回答动辄几十万字符，`textContent` 更快也更安全。
只有 judge 的评分原文走极简 markdown 渲染（**先转义再套正则**）。

---

## 目录

```
trace-viewer/
├── viewer/
│   ├── index.html        查看器本体（单文件，无外部依赖）
│   ├── build_viewer.py   数据编译（raw+judged → index.js + cells/）
│   └── serve.py          增强服务器（Range + gzip + 缓存头）
├── demo/
│   ├── make_demo.py      合成演示数据生成器
│   ├── build-demo.sh     重新编译演示站点到 docs/
│   ├── config.json       演示配置
│   └── data/             合成原始数据（144 条样本）
├── docs/                 GitHub Pages 发布根 = 编译好的演示站点
│   ├── index.html / index.js / cells/ / download/
│   └── data-format.md    数据格式完整说明
└── LICENSE               MIT
```

---

## 环境

Python 3.10+（用到 `match`/海象运算符）。前端无依赖，任何现代浏览器。

## License

MIT
