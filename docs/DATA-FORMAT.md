# 数据格式

查看器只吃两个目录。文件名约定 `row<题号4位>.s<采样号>.json`。

```
raw/<source>/rowNNNN.sK.json
judged/<source>/judged/rowNNNN.sK.json
```

- `<source>` 短的源标签，也是矩阵里的列；显示名用 config 的 `sources[].name` 覆盖
- `row0007.s3.json` = 第 7 题、第 4 次采样（索引从 0 起）
- **所有字段都可选**，缺了就不渲染对应块

---

## 采样记录 `raw/…`

| 字段 | 类型 | 用途 |
|---|---|---|
| `row_index` | int | **必需**。题目序号，决定矩阵的行 |
| `s_idx` | int | **必需**。采样序号（0..N-1） |
| `subject` | str | 学科，用于按学科筛选 |
| `question` | str | 题面，展示在「📋 题目原文」 |
| `gold` | str | 评分标准，展示在「🎯 官方评分标准 gold」 |
| `thinking_text` | str | 模型思考 → 「🧠 模型思考过程」 |
| `answer_text` | str | 模型正文（原始） |
| `answer_visible` | str \| null | **judge 实际打分对象** → 「✍️ 模型最终回答」。为 null/空且 `skip_empty=true` 时按空答案处理 |
| `finish_reason` | str \| null | `stop` 正常 / `length` 打满 max_tokens / `null` 流被掐断 |
| `usage.prompt_tokens` | int | 输入 token |
| `usage.completion_tokens` | int | 生成 token 总数 |
| `usage.completion_tokens_details.reasoning_tokens` | int | **思考** token。回答 token = `completion_tokens - reasoning_tokens` |
| `usage.reasoning_tokens` | int | 同上，部分服务放顶层；两者取其一 |
| `elapsed_s` | float | 该次墙钟耗时（秒） |
| `attempts` | int | 网络层重试次数，>1 会额外标出 |
| `error` | str \| null | 失败原因，非空会红字显示 |
| `skip_empty` | bool | 空答案标记（仅影响展示文案） |

## 判分记录 `judged/…`

| 字段 | 类型 | 用途 |
|---|---|---|
| `row_index` / `s_idx` | int | **必需**。与采样记录对齐 |
| `reward` | float \| null | 最终分，与 `solved_fraction` 比较决定「解出」 |
| `points_median` | float \| null | 中位 points（满分 10），展示用 |
| `votes` | str | 每票一个字母，如 `CCI`（`C`=解出，`I`=未解出）。用于一眼看三票分歧 |
| `skipped` | bool | `true` = 空答案短路，**未调用 judge**；页面会显示灰底标签并说明 |
| `votes_detail[]` | list | 逐票明细，展开后可见 |

`votes_detail[]` 每项：

| 字段 | 用途 |
|---|---|
| `points` / `fraction` | 该票得分（0-10 / 0-1） |
| `verdict` | `C` / `I`，单字母结论 |
| `content` | **judge 的评分原文**（逐条 rubric 打分）→ 「📄 judge 评分原文」 |
| `reasoning_content` | **judge 的推理过程** → 「🤔 judge 推理过程」 |
| `extract_content` | 二次抽取出的总分（如果判分是两段式） |
| `duration_s` | 该票耗时 |
| `reasoning_effort` / `model` | judge 的元信息 |
| `usage.completion_tokens` | 该票生成 token |
| `usage.completion_tokens_details.reasoning_tokens` | 其中推理 token（`content` 部分的 token 由差值推出） |

---

## 字段怎么变成页面上的块

```
raw.question              →  📋 题目原文            prompt
raw.gold                  →  🎯 官方评分标准 gold    rubric
raw.thinking_text         →  🧠 模型思考过程         reasoning_content
raw.answer_visible        →  ✍️ 模型最终回答         answer_visible   ★ judge 打分对象
judged.votes_detail[].content            →  📄 judge 评分原文   ★ 逐条打分
judged.votes_detail[].reasoning_content  →  🤔 judge 推理过程
```

★ 两块最关键：**模型最终回答**是「被判的东西」，**judge 评分原文**是「判的结果和理由」。

---

## 派生指标（由 build_viewer.py 计算，不需要你提供）

| 指标 | 算法 |
|---|---|
| 格子里的 `x/y` | `x` = 该题该源 6 次采样中 `reward ≥ solved_fraction` 的次数；`y` = `reward` 非 null 的次数 |
| `pass@1` | 逐题算「解出数 / 有效数」，再对全部题求平均 |
| `pass@N` | 逐题算 `1 - C(y-x, N)/C(y, N)`，再对全部题求平均（N = 采样数） |
| 题目难度 | 该题上所有源的「解出数 / 有效数」 |
| `mean points` | 所有有效样本 `points_median` 的均值 |

---

## 注意

- **`reward` 为 null** 的样本（判分失败）不计入 `y`，页面标为「判分失败」。
- **`skipped=true`**（空答案短路）**计入 `y`**，按 `reward` 的值（通常是 0）算 —— 因为
  「没答出来」本身就是 0 分，不该从分母里剔除。
- 若你的判分记录不在 `judged/<source>/judged/` 而在 `judged/<source>/`，也能识别
  （build 脚本会先试 `judged/` 子目录，失败再试当前目录）。
