# P4/P3 指标优化计划（数据收集路线落地版）

> 承接 [PROJECT_PLAN.md](PROJECT_PLAN.md) §七「阶段成果记录」与文末「P4/P3 指标优化优先级（数据收集路线，定稿）」，并把它
> 扩展为**可执行**的计划：把用户新提供的三条数据采集路线（Google BigQuery 导出 / USPTO ODP·PatentsView key /
> Benchmark 对标）落到「哪个指标、怎么救、何时救」。
>
> 现状数字全部来自 [P3_OPT_P4_RESULT.md](P3_OPT_P4_RESULT.md)，根因已在 P3/P3.5 多组对照中锁定，本文不重复论证，只排优先级与落地路径。

> ⚠️ **执行结果更新（2026-09-23）**：P0-1 已交付（6,967,772 条前向引用、2015→2024、免 key），
> 但 **P2-1 立项前提被证伪**——专利引用图在 walk-forward + 转导协议下必然退化，不能作 CyGNet 的 TKG 边源。
> 本计划「关键路径 P0-1→P1-2→P2-1」在 P2-1 处断裂；P0-1 产物仍服务 P1-2（引用回归 + S 曲线）。
> 详见 [P4_P3_METRIC_OPT_RESULT.md](P4_P3_METRIC_OPT_RESULT.md)。

---

## 0. 一页结论

| 目标 | 指标 | 当前值 | 一句话根因 | 主救手段（本计划） |
|---|---|---|---|---|
| ① 新兴/热门识别 | precision@k / recall@k | **0.0 / 0.0** | Kleinberg 突发与「未来增速 top-k」在月度粒度不重合，信号弱 | 真引用/star/专利时序做真值 + Benchmark 口径对齐 |
| ② 链接预测外推 | CyGNet MRR（定向图） | **0.1621 < RotatE 0.2390** | 定向图稀疏 + 86.5% 测试是新链接，copy 无史可复 | **专利前向引用图**（定向+时态+高重复）+ 每日增量累积历史 |
| ② 链接预测外推 | CyGNet MRR（共现图） | 0.9459 ≫ RotatE 0.4487 | 共现图高复现，copy 轻松赢（对照） | 说明「重复性」是 CyGNet 燃料，专利引用图正合此特性 |
| ③ 指标时序外推 | MAE / RMSE / MAPE | 0.5017 / 0.5269 / 1.9166 | 代理信号 = 「月度活动量」，非真引用/star/专利量 | OpenAlex `cited_by_count` + USPTO 前向引用时序 |
| ④ 成熟度 S 曲线 | — | 未做（留 P6） | 缺前向引用/引用增速时序 | USPTO 前向引用曲线（引用加速→饱和） |

**三条数据路线 → 指标映射**：

| 路线 | 免 key？ | 直接救的指标 | 优先级落位 |
|---|---|---|---|
| **① USPTO 前向引用数据**（PatentsView bulk 或 BigQuery，均免 key） | ✅ 免 key、立即 | 目标②（Patent→Patent 引用边）+ 目标③④（引用时序） | **P0** |
| ② USPTO ODP / PatentsView key | ❌ 需注册 | 目标②③④ 的**每日增量**自动化（历史批量用 BigQuery） | P1（自动化备份） |
| ③ Benchmark 对标（PwC/HF/综述/Model Zoo） | ✅ | 目标①②③ 的**外部基线 + 口径对齐** | P1 |

> **本计划对现有「优化优先级」的最大改动**：原表把「USPTO 前向引用时序」放在 **P2**（因为当时判定需等 ODP key）。
> 现确认 **BigQuery 公开数据集免 key 即可导出全量引用图**，故把它**上提到 P0**——它同时是目标②（CyGNet 缺「可复制历史」）
> 和目标③④（缺真引用时序）的同一个解。

---

## 1. 现状基线（承 P3_OPT_P4_RESULT，不重复论证）

四目标验收口径已在 P3.5/P4 固化：TKG filtered MRR/Hits@1/3/10（时态、同时态同协议）、回归 MAE/RMSE/MAPE、
排名 precision@k/recall@k、walk-forward + purge/embargo 防泄漏。当前卡点只有两个，且**都是数据形状问题，不是实现 bug**：

1. **目标② A2 未达标**：CyGNet 靠「复制历史」，但 LLM 抽的定向 tech→tech 边只有 1136 条、测试 86.5% 是「新链接」，
   copy 无史可复，只剩 generate（DistMult）跟 RotatE 对拼而落败。**反超的唯一杠杆 = 喂给 CyGNet 更多「可复制的历史」**。
2. **目标③④ 语义失真**：回归与排名用「月度活动量」做代理，不是真引用/star/专利量，因此 p@k=0、MAE 无真实意义。

这两点的共同解，正是用户新给的三条数据路线——**专利前向引用图**天然是「定向 + 时态 + 高度重复」的边（同一领域的专利反复引用
同一批奠基性专利），恰好是 CyGNet copy 的猎物；同时给出真引用时序，把目标③④的 ground truth 从代理换成真实量。

---

## 2. 三条数据采集路线落地

### 路线① USPTO 前向引用数据获取（免 key，P0）—— 两条子路线

**先给结论：不依赖 ODP key。前向引用有两条真正免 key 的路，ODP key 只在「每日增量 API」这一环才需要，可整体推迟到 P5。**
历史批量用下面任一条路即可，不影响目标②③④的落地。

**子路线 A：PatentsView bulk 下载（零门槛，首选）** —— 无 key、无账号、无计费，直接 HTTP 下载引文对表再本地反转。
这正是本项目已有「本地 bulk XML」模式的延续，最贴合现有 pipeline（data/raw 已有 USPTO 周文件）。

| 文件 | 用途 |
|---|---|
| `https://s3.amazonaws.com/data.patentsview.org/download/uspatentcitation.tsv.zip` | 引文对表（`patent_id` ↔ `citation_id`），**前向引用 = 反转**（citation_id 为被引专利） |
| `.../patent.tsv.zip` | `patent_id` → 专利号/授权日映射（join 用） |

> 下载整个引文对表（压缩后数百 MB～GB 级），本地 join + 反转即得前向引用。缺点是 US-only + 无法服务端过滤。

**子路线 B：BigQuery sandbox（免 key + 免计费，需免费 Google 账号）** —— 服务端 SQL 过滤，一条查询筛「多日 + 多国 + CPC」，不用下载整表。
**为什么用它**：公开数据集每月 1 TB 免费查询额度、**sandbox 模式无需绑信用卡/开计费**、SQL 直接筛主题，**完全绕开**「下载并解析海量原始 .zip」的笨办法。

**怎么选（按指标提升 / 数据质量 / 处理效率）**：前向引用是「**任意技术领域的专利都可能引用你的 G06N 专利**」，即引用侧不能按 CPC 窄筛、必须拿整张引文图。这恰好抵消了 B 的「服务端窄筛」优势——B 要算前向引用，要么对 7600 万行表做 self-join（代价高、几次查询就逼近 1TB 免费额度），要么先物化子集再 join（多几步）；而 A 一次性下载整张引文对表、本地反转，确定性、零配额、零查询优化风险。数据质量上，PatentsView 是 US 同源完整引用；BigQuery 多国引用完整性不均（US 全、CN/JP/KR 稀疏），对 G06N（AI/CS 专利高度集中 US）多国的边际增益小。**结论：A 主（建图）+ B 辅（快速计数/覆盖检查，或日后要全球专利时再用）。**

**数据集与表**（Google Cloud → BigQuery → 公开数据集）：

| 表 | 用途 | 关键字段 |
|---|---|---|
| `patents-public-data.patents.publications` | Google Patents 研究数据：专利书目 + 反向引用（每篇专利引用了谁） | `publication_number` / `country_code` / `publication_date` / `cpc`(REPEATED `.code`) / `citation`(REPEATED `.publication_number`) |
| `patents-public-data.uspto_oce_citations.citation` | USPTO OCE 引文对表（专利→被引专利） | `patent_id` / `citation_id` / 日期字段（**以控制台实际 schema 为准**） |
| `patents-public-data.patentsview.*` | PatentsView bulk 载入 BigQuery（含 `uspatentcitation` 引文对） | `patent_id` / `citation_id`（**以控制台实际 schema 为准**） |

> ⚠️ 表名/字段名会随数据集更新而变化，**开工第一步先打开 BigQuery 控制台核对 schema**，不要照抄本文字段名。
> `patents.publications` 表极大（亿级行），必须用 `publication_date`（分区）与 `country_code`/`cpc`（聚簇）过滤，避免全表扫描烧额度。

**SQL 草图（前向引用 = 反向查「谁引用了我」）**：

```sql
-- 导出 G06N(AI/ML) 主题的专利，及其「前向引用」：所有引用本专利的后续专利
SELECT
  p.publication_number AS patent,
  p.country_code, p.publication_date,
  cpc.code AS cpc,
  cited.publication_number AS cited_by,   -- 引用 p 的专利
  cited.publication_date AS cited_by_date -- 引用发生时间（时序关键）
FROM `patents-public-data.patents.publications` AS p
JOIN UNNEST(p.cpc) AS cpc
JOIN `patents-public-data.patents.publications` AS cited
  ON cited.citation.publication_number = p.publication_number   -- 反向：cited 引用了 p
WHERE STARTS_WITH(cpc.code, 'G06N')
  AND p.publication_date >= '2020-01-01'
  AND p.country_code IN ('US','EP','CN','JP','KR','WO')          -- 多国
```

> 具体「反向 join」写法取决于 `citation` 字段是 REPEATED 还是需 `UNNEST`，**以控制台 schema 为准**。导出为
> `data/raw/uspto_forward_citations.csv` 或直接 `data/interim/patent_citations.jsonl`，落进现有 pipeline。

### 路线② USPTO ODP / PatentsView key（P1，自动化每日增量）

**key 校验结论**：你给的 `bm9kZGVkbGFiZWxwb29yc2hhcnB3YXlhZGRpdGlvbmFsdG9iYWNjb2xpc3RwaW5ldG8=` 解码后是
`noddedlabelpoorsharpwayadditionaltobaccolistpineto`——**一个占位/测试串，不是有效 key**（ODP key 是 data.uspto.gov
签发的正式 token）。需注册真实 key 才能测：

1. **注册**：[data.uspto.gov](https://data.uspto.gov) → MyODP → 用 USPTO.gov 账号（需 **ID.me 实名验证**）创建 API key。
2. **认证**：请求头 `X-API-Key: <你的key>`（不是 Bearer）。
3. **前向引用端点**（PatentsView 已并入 USPTO ODP 的 **PatentSearch** API，旧版 2025-05-01 停用）：
   - `GET https://api.uspto.gov/api/v1/patent/us_patent_citation/{patent_id}` —— 该专利的引文记录；
   - **前向引用**按 `citation_patent_id` 过滤（= 被引专利 = 目标专利），**反向引用**按 `patent_id` 过滤；
   - 字段：`patent_id` / `citation_patent_id` / `citation_date` / `citation_category` / `citation_wipo_kind`。
4. **测通标志**：`X-API-Key` 正常、返回该专利的 `citation_patent_id` 列表非空。

> 分工：**BigQuery 负责历史批量（P0，一次性/定期大导出）；ODP key 负责每日增量（P1，补当天新授权专利的引用）**。
> 两者字段都要落到同一个 `patent_citations.jsonl` 契约，避免两套 schema。

### 路线③ Benchmark 对标（P1，外部基线 + 口径对齐）

**为什么做**：现在 `tkg_mrr=0.9459`（共现图）没有参照系——「0.95 到底好不好」只能跟已发表的基准比。PROJECT_PLAN §5.4 已列
对标对象：**ICEWS14/18、TGB、AIPatent**（AI 专利 TKG，与本项目专利引用图直接对齐）、**Science4Cast**（语义网络链接预测，
AUC 0.94–0.99 的评测范式）。本计划把「收集这些基准的数字 + 对齐口径」变成一项明确任务。

**高效收集路径**（按你的方法归纳，从快到慢）：

| 路径 | 适用 | 例子 |
|---|---|---|
| SOTA/排行榜平台 | 各任务主流指标一屏看全 | Papers with Code（按任务搜）、HuggingFace Leaderboards（NLP/LLM）、OpenCompass / LMSYS Chatbot Arena（大模型） |
| 综述对比表 | 横向数十方法一表打尽 | 近 1–2 年 TKGC/科技预测综述（Cai 2022 等）的 comparison table |
| 官方 Model Zoo / 复现 log | 最准、去参数差异 | 目标方法官方 README/MODEL_ZOO.md 的原始指标；AIPatent/ICEWS 复现仓库的 eval log |

**口径对齐四条守则**（你列的「核心注意事项」落到本项目）：

| 维度 | 本项目对照 | 红线 |
|---|---|---|
| 指标一致 | TKG 一律报 **filtered** MRR/Hits（不跟 raw 混比）；回归统一 MAE/RMSE/MAPE | 不把随机切分 MRR（P2=0.2734）与时态切分 MRR（P4=0.9459）混比 |
| 数据切分 | 与 ICEWS/Science4Cast 对齐「时间切分」，禁用 shuffle；train<val<test 时间不重叠 | 严禁用训练集数据对比 |
| 评测设置 | LLM 抽取结果标注是 few-shot / zero-shot / 微调；引用数与 FPS 类的硬件敏感项单独注明 | 不拿 A100 的 FPS 对比 V100 |
| 真值来源 | 前 N 年 → 预测后一月，真值 = 事后发生的事实 | 目标②③④ 各有独立真值，不交叉 |

---

## 3. 指标优化优先级 P0 / P1 / P2

### P0（立即开工，直接决定目标② A2 是否达标 + 解 B1-TKG 回退）

| # | 项 | 救哪个指标 | 手段 / 数据源 | 交付物 | 验收 |
|---|---|---|---|---|---|
| P0-1 | **USPTO 前向引用图（PatentsView bulk / BigQuery）** | 目标②（给 CyGNet 喂「可复制的历史」） | PatentsView bulk 下载引文对表本地反转，或 BigQuery `patents-public-data` 导出 Patent→Patent 引用边（定向+时态+高重复，同一领域反复引用同一批奠基专利） | `data/interim/patent_citations.jsonl`（head/tail/time 契约） | 引用边 > 5000 条、时态跨 2015→2026、无 key 跑通 |
| P0-2 | 重跑 `--stage extract` 补近期定向对（#19） | 目标②（解 B1-TKG 回退）+ A2 补历史 | `works.jsonl` 已含 2026-09 作品，仅定向 pass 未重跑 | triples 近期定向对进图 | B1 TKG 不再回退到共现投影；定向图事实数上升 |
| P0-3 | 启动每日增量（#20，P5 cron） | 目标②（(s,r) 跨时间重复 = copy 燃料） | collect→extract→align 每天跑，累积时序深度 | `cron.py` 每日无人值守 exit 0 | 连续 3 天增量不重复、时序深度递增 |

> **P0-1 是本计划的关键新增**：它绕开了「LLM 定向对稀疏」这个 P3.5 没有解掉的死结——专利引用不是 LLM 抽的、不存在幻觉，
> 而且天然「高重复」，正好命中 CyGNet copy 的假设。预期在专利引用 TKG 上 copy 反超 RotatE（共现图已证明这一点）。

### P1（救目标③④ 语义真实性 + 目标① p@k + 外部对标）

| # | 项 | 救哪个指标 | 手段 / 数据源 | 交付物 | 验收 |
|---|---|---|---|---|---|
| P1-1 | OpenAlex `cited_by_count` 入 works + GitHub 多日 star 快照（#9） | 目标③（真引用/star 时序，替换「月度活动量」代理） | `openalex.normalize` 补 `cited_by_count`（`_SELECT` 已含、仅 normalize 丢弃，**1 行修复**）；github 对同仓库多日快照 | works 带 `cited_by_count`；`github_stars.jsonl` 多日 | 回归目标从「活动量」换成真引用/star，MAE 有真实语义 |
| P1-2 | USPTO 前向引用时序 → 目标③④（#5 落地） | 目标③（专利引用时序真值）+ 目标④（S 曲线成熟度） | 用 P0-1 的引用边，按概念/专利聚合「累积前向引用曲线」 | `forecast.csv` 用引用真值；概念级引用曲线 | 回归 MAE/RMSE/MAPE 换成引用量口径；目标④ 出 S 曲线阶段标签 |
| P1-3 | Benchmark 外部基线 + 口径对齐（新） | 目标①②③（让 0.9459 / MAE / p@k 有参照系） | §路线③ 收集 ICEWS/AIPatent/Science4Cast 数字，按 §口径守则对齐 | `benchmark_comparison.md` | 报告可写「本系统 MRR X vs AIPatent 基线 Y」，口径一致 |

> **P1-3 的定位**：不是新算法，是把「我们做得好不好」从「自己跟自己比」变成「跟已发表基准比」。落地时先对齐口径
> （filtered / 时态切分 / 同真值），再写对比结论，避免「用不同口径的数字硬比」。

### P2（次级，按需）

| # | 项 | 救哪个指标 | 触发条件 |
|---|---|---|---|
| P2-1 | 专利引用 TKG 边源集成（AIPatent 对齐） | 目标② A2 反超的模型侧落地 | P0-1 引用边就绪后，把它作为 `tkg_edge_source=patent_citation` 第三种边源接入 `_run_tkg`/evaluate；与 AIPatent 基准直接可比 |
| P2-2 | 定向抽取全源近期覆盖（#21） | 目标②（加密定向图） | 定向 pass 从 OpenAlex 扩到 arXiv/USPTO/GitHub/RSSHub（经 Concept 对齐） |
| P2-3 | GDELT 多日（#14）+ competes/causes（#15）+ GRU generate（#3） | 目标①②③ 边角 | GDELT 连续多天成时间序列；补含竞品/因果的文档让规则更丰富；数据量上来后开 GRU 序列化 generate |

---

## 4. 口径守则（贯穿 P0–P2）

1. **只「补数据 / 补历史」，不「调参数到赢」**（#18）：所有改动必须落在数据层（加引用边、加真值时序、加大时间跨度），
   禁止通过调 `tkg_min_cooccur` / `techpair_min_support` / `tkg_alpha` 来「凑出」A2 反超；若调参须有原则依据 + 报告中如实说明。
2. **同时态同协议对比**：目标② 坚持 CyGNet 时态 vs RotatE 时态，不与 P2 随机切分（0.2734）混比；walk-forward mean±std 为对外口径。
3. **filtered 口径 + 时间切分 + 无泄漏**：引用图 TKG 同样走 `evaluate.py` 的 walk-forward + purge/embargo + leak_check，不另起炉灶。
4. **真值独立**：目标②（新关联）、③（未来引用量）、④（S 曲线阶段）各有独立真值，引用边只喂 ③④ 与 ② 的候选打分，不拿「引用」当「技术关联」真值混用。
5. **诚实报告**：若专利引用图上线后 A2 仍不达标，回到兜底 ②（copy-only ≥ DistMult 同量级 或 结构完整+可解释+回归/融合全通）如实收尾，不造假。

---

## 5. 实施顺序与依赖

```
P0-2（重跑 extract，~10 分钟，无新依赖）
  └─► P0-1（BigQuery 导出引用边，半天：核对 schema + SQL + 落 jsonl）
        └─► P0-3（cron 每日增量，随 P5 启动）
P1-1（cited_by_count 1 行修复 + star 快照，~1 小时）—— 可与 P0 并行
P1-2（引用时序 → 回归真值 + S 曲线，依赖 P0-1 产物）
P1-3（Benchmark 收集 + 口径对齐，独立，可与 P0 并行）
P2-1（引用图接入 TKG 边源，依赖 P0-1 + P1-2）—— A2 反超的最终落点
P2-2 / P2-3（按需，依赖数据量增长）
```

**关键路径**：`P0-1 → P1-2 → P2-1`（引用图从「拿到数据」到「接入 TKG 反超 RotatE」）。这条链同时解目标②（copy 燃料）与
目标③④（真时序），是本次优化的主轴；P0-2/P0-3 是保底补历史，P1-1/P1-3 是救语义与对标，均可并行推进。

> ⚠️ **P2-1 已证伪（2026-09-23）**：上述关键路径的终点 P2-1（引用图反超 RotatE）经实测不成立
> （时态 DAG → 转导退化 + 单事件边无 copy 燃料），见 [P4_P3_METRIC_OPT_RESULT.md](P4_P3_METRIC_OPT_RESULT.md)。
> 关键路径改道为 `P0-1 → P1-2`（引用时序回归 + S 曲线，仍成立）；P1-1 / P1-3 不受影响可继续；
> A2 反超不再走「专利引用图」路线。

---

## 附：待办登记（跨 P5/P6）

- 每日增量累积时序深度（#20）—— P5 cron 落地后，A2 反超的时间杠杆。
- 目标④ S 曲线阶段 + 趋势图 + 周报 —— P6。
- hermes-agent cron + 角色化 agent —— P5。
- 根目录残留调试脚本 `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删。
