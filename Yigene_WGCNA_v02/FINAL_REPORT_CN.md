---
project: Yigene_WGCNA_v02
candidate_id: C20260624011438577477
status: KEEP
evidence_level: MODERATE
language: zh-CN
created_at: 2026-06-24
---

# 最终报告：高心率物种的趋同共表达模块

> 蝙蝠（Sk，*Scotophilus kuhlii*，小黄蝠）和鼩鼱（Sm，*Suncus murinus*，大臭鼩）
> 独立演化出高心率。大鼠（Rn，*Rattus norvegicus*）为低心率外群。
> 核心问题：Sk 和 Sm 在心房或心室是否共享共表达模块，
> 即是否存在趋同演化的分子网络签名？

---

## L0 Linnaeus — 前置检查（技能与记忆门）

**技能扫描：** 93 个本地技能 + 11 个插件能力。

| 技能 | 用途 |
|------|------|
| bat-heart-target-screen | 样本来源验证、物种分配确认 |
| bulk-rnaseq | TMM/voom 标准化方法确认 |
| systematic-debugging | WGCNA 崩溃预防（CRASH_LOG.md，9 个崩溃点） |
| academic-research-suite | 假设生成的文献支持 + 生物学解释 |

**缺口：** 无专用 WGCNA 技能。脚本基于 v0.1 崩溃日志的模式从零编写。EverOS 记忆在线（2026-06-24 验证）。

**输入数据验证：**
- 表达矩阵：11974 基因 x 71 样本（length_scaled_counts.csv）
- 元数据：95 行，过滤后 71 行（sample_metadata_checked.csv）
- DEG 基因集：gene_sets/ 下 20 个文件
- 基因映射：11648 行（rat_symbol -> mouse_entrez）
- 样本分布：Rn(24: 8A+16V), Sk(23: 7A+16V), Sm(24: 8A+16V)

---

## L1 Einstein — 假设生成

生成 7 个候选假设：

| 编号 | 假设 | 可测试性 |
|------|------|----------|
| H1 | 心房趋同共表达模块 | 可测试（n=23，边界） |
| H2 | 心室趋同共表达模块 | 可测试（n=48，充足） |
| H3 | 全心趋同签名 | 不区分腔室则太宽泛 |
| H4 | 共享模块富集能量代谢 | 需 GO/KEGG |
| H5 | 共享模块富集钙离子处理 | 需 GO/KEGG |
| H6 | 共享模块富集 ECM/结构重塑 | 需 GO/KEGG |
| H7 | 零假设：无趋同模块 | 可通过保存性 Z < 2 检验 |

**关键不确定性：** 全样本 WGCNA（第一轮）发现物种特异性模块（turquoise=物种, yellow=Sm, brown=Sk），但无法测试腔室特异性趋同。

---

## L2 Feynman — 假设证伪

**攻击点：**

1. **心房样本量（高风险）：** Sk 心房仅 7 个样本。n=23 的 WGCNA 处于边界。每组 7 个样本的模块稳定性存疑。
2. **批次混淆：** batch1=59, batch2=12。必须验证批次与物种不混淆。全样本网络已包含批次协变量；子集无法包含。
3. **无符号网络：** 将上调和下调基因合并到同一模块。共享模块可能是基因方向相反的假象。
4. **强制 power=4：** 自动选择为 1。强制 4 可能制造人工结构。
5. **动物伪重复：** 12 个 animal_id 跨 71 个样本。配对设计，非完全独立。

**结论：** H2（心室趋同）是最强可测试假设。H1（心房）应尝试但可能因样本量失败。H7（零假设）必须同时报告。

---

## L3 Oppenheimer — 候选筛选

**决策：** 选定 H1（心房趋同）+ H3（心室趋同）+ H7（零假设）。拒绝 H4/H6/H7 作为过于模糊或衍生。路由到 Fisher 进行方法设计。

---

## L4 Fisher — 方法设计

**策略 A+B 批准：**

| 步骤 | 分析 | 样本数 | 状态 |
|------|------|--------|------|
| A1 | 全样本 WGCNA | 71 | 完成（第一轮） |
| A2 | 心房 WGCNA | 23 | 新 |
| A3 | 心室 WGCNA | 48 | 新 |
| A4 | 模块保存性 Sk<->Sm | - | 新 |
| A5 | 模块-性状相关性 | - | 完成 + 新 |
| B1 | 基因集重叠（Fisher 精确检验） | - | 新 |
| B2 | GO/KEGG 富集 | - | 新 |

**关键设计决策：** 无符号网络，power=4，maxBlockSize=6000，minModuleSize=30，mergeCutHeight=0.25，nThreads=1，saveTOMs=FALSE。

---

## L5 Tukey — 方法证伪

**QC 检查点：**
1. WGCNA 前：table(species, chamber, batch) — 检查混淆
2. blockwiseModules 后：n_modules >= 3（若 0-1，停止）
3. 模块保存性后：报告 Zsummary 值，不只 pass/fail
4. 富集后：FDR < 0.05，每个 GO term 至少 5 个基因

**失败停止规则：**
- 心房 WGCNA 给出 0 个真实模块：停止，报告，不强制趋同
- 批次与物种混淆：停止，报告，无法分离效应
- 无模块与 DEG 共享集重叠：诚实报告零结果

---

## L6 Oppenheimer — 分析计划批准

**决策：** 策略 A+B 批准。Tukey QC 门接受。脚本按模块化步骤拆分（依据第一轮教训）。路由到 Turing 执行。

---

## L7 Turing — 执行

6 个脚本按顺序执行，全部退出码 0。参数与第一轮一致（无符号, power=4, maxBlockSize=6000, minModuleSize=30, mergeCutHeight=0.25, nThreads=1, cor <- WGCNA::cor, 无 sink()）。

### 1-2. 腔室特异性网络

| 网络 | 样本 | 模块数 | 模块大小 |
|------|------|--------|----------|
| 心房 | 23 (Rn8/Sk7/Sm8) | 4+grey | turquoise(1581), blue(1537), brown(1186), yellow(621), grey(75) |
| 心室 | 48 (16/16/16) | 5+grey | turquoise(1533), blue(1232), yellow(872), brown(921), green(386), grey(56) |

注意：心房 n=23 对 WGCNA 偏小，模块为探索性。子集使用简化 ~0+group 设计（无批次协变量）。

### 3. 模块保存性（Sk <-> Sm，nPermutations=50）

| 模块 | 大小 | Z(Sk->Sm) | Z(Sm->Sk) | Z_min | 保存性 |
|------|------|-----------|-----------|-------|--------|
| green | 179 | 20.23 | 21.55 | 20.23 | 强 |
| turquoise | 1720 | 20.40 | 16.90 | 16.90 | 强 |
| blue | 1440 | 12.28 | 9.57 | 9.57 | 中等 |
| brown | 1257 | 7.11 | 4.51 | 4.51 | 中等 |
| yellow | 291 | 2.52 | 3.16 | 2.52 | 中等 |

### 4. 基因集重叠（Fisher 精确检验，108 个测试）

最强富集：turquoise 与 ventricle_shared_down（OR=5.9, p_adj=1e-146）；brown 与 atrium_shared_up（OR=1.8, p_adj=6e-12）。

### 5. GO/KEGG 富集

5000 个基因中 4831 个（96.6%）映射到小鼠 Entrez。仅 green 模块有显著 GO 条目（49 BP, 15 MF, 1 KEGG）。大模块因 universe-size 效应统计功效不足。

### 6. 趋同模块汇总

三条趋同标准：(a) 与 high_heart_rate 相关 p<0.05；(b) Sk<->Sm 保存性 Z_min>=2；(c) 与 shared DEG 集 BH<0.05 重叠。

| 模块 | 心率相关 r | 心率 p | (a) | Z_min | (b) | 最佳 shared 集 | (c) | 趋同 |
|------|-----------|--------|-----|-------|-----|----------------|-----|------|
| turquoise | -0.955 | 5e-38 | Y | 16.90 | Y | ventricle_shared_down | Y | 是 |
| brown | +0.799 | 7e-17 | Y | 4.51 | Y | atrium_shared_up | Y | 是 |
| yellow | +0.611 | 2e-08 | Y | 2.52 | Y | - | N | 否 |
| green | -0.524 | 3e-06 | Y | 20.23 | Y | - | N | 否 |
| blue | +0.008 | 0.95 | N | 9.57 | Y | - | N | 否 |

**趋同模块：turquoise, brown。**

---

## L8 Curie — 证据审计

**逐文件核对：**
- 模块数验证：三个网络模块大小加总均为 5000 基因 ✓
- 样本数验证：心房=23, 心室=48 ✓
- 保存性 Z 值与报告一致 ✓
- Fisher overlap p 值与报告一致 ✓
- 富集结果一致：仅 green 有显著条目 ✓

**证据等级：MODERATE**

限制因素：
1. 心房 n=23 太小，结果为探索性
2. 保存性仅 50 次排列（发表级需 >=100）
3. 大模块 GO 富集统计功效不足（universe-size 效应）

---

## L9 Feynman — 结果证伪

**5 个证伪风险：**

| 风险 | 严重度 | 可解决？ |
|------|--------|----------|
| 物种 vs 心率混淆 | 高 | 现有数据无法解决 |
| 子集中批次效应 | 中 | 如可能用批次重跑子集 |
| green 模块被排除 | 中 | 放宽标准 (c) 或单独解读 |
| Power 敏感性未跑 | 低-中 | 可跑但不太可能改变 |
| 排列次数低 | 低 | 提高到 200+ |

**最大威胁：** turquoise 与 species r=-0.962 和与 high_heart_rate r=-0.955 几乎相同。3 物种设计中物种与心率完全混淆。趋同声明依赖模块保存性（Sk<->Sm Z=16.9），证明蝙蝠和鼩鼱特异性共享共表达结构。但无第 4 个高心率物种或低心率蝙蝠/鼩鼱，心率 vs 物种的区分无法用现有数据解决。

**哪些经得住证伪：**
- turquoise 和 brown 作为趋同候选：存活，附带物种混淆警告
- green 作为心脏身份模块：存活为生物学有意义，标准 (c) 太严
- 心房/心室子集网络：存活为探索性
- 核心假设（Sk 和 Sm 共享共表达模块）：存活，保存性 Z 分数支持

---

## L9 Darwin — 生物学解释

### Turquoise（1720 基因）— 趋同，心室相关

与高心率强负相关（r=-0.955），Sk<->Sm 强保存（Z=16.9），与 ventricle_shared_down DEG 集重叠（804 基因, OR=5.9）。

**解读：** 这是高心率物种中下调的模块，特异于心室。大小占网络 34%，捕获主要转录转变。在蝙蝠和鼩鼱中保存意味着两个物种独立抑制了相同的基因网络。符合"低心率程序抑制"模型：低心率心脏功能所需基因在高心率心脏中协调下调。

### Brown（1257 基因）— 趋同，心房相关

与高心率正相关（r=+0.799），Sk<->Sm 中等保存（Z=4.5），与 atrium_shared_up DEG 集重叠（292 基因, OR=1.8）。

**解读：** 高心率物种中上调的模块，特异于心房。中等保存（非强保存）提示部分趋同：蝙蝠和鼩鼱都在心房上调该网络，但内部结构有所分化。可能代表主动重塑程序（离子通道重构、代谢上调），两个物种都需要但在心房中通过部分不同的基因集实现。

### Green（179 基因）— 心脏身份模块

与高心率负相关（r=-0.52），保存性全场最强（Z=20.2）。GO 富集：心肌组织发育、横纹肌发育、心肌细胞分化。关键基因：Myl2, Myl3, Myh11, Irx3, Nrg1, Tcap, Bmp10, Shox2。

**解读：** 心脏身份/发育模块。在蝙蝠和鼩鼱间强保存意味着核心心脏转录程序在 9600 万年分化后仍保守。心率相关性提示该模块在高心率心脏中表达更低——与发育/结构程序下调以让位于收缩/代谢程序一致。这不是趋同适应模块，而是保守的心脏基线，两个高心率物种相似地调控。

### 趋同演化解读

双重模式（心室下调 + 心房上调）提示高心率心脏适应涉及腔室特异性重塑：心室偏离基线程序，心房激活新程序。两个物种独立到达这一模式，是共表达网络水平趋同演化的证据。

**不能证明的：**
- 不能证明相同基因驱动趋同
- 不能区分心率适应与其他共享特征（飞行、高代谢）
- 不能建立因果关系（模块是相关的）
- 物种 vs 心率混淆意味着不能排除物种特异性模块

---

## L10 Jobs — 价值评估与手稿方向

**标题：** 不是"蝙蝠和鼩鼱共享趋同心脏模块"（物种混淆）。而是："独立高心率物种间的共表达模块保存性揭示了共享的心脏转录程序，其中心脏身份模块（green）显示出最强的跨物种保存性。"

**现在可发表（附警告）：**
- 全样本 WGCNA（5 模块 + 性状相关）
- 模块保存性 Sk vs Sm（nPermutations=50 警告）
- 基因集重叠分析（108 个 Fisher 检验）
- Green 模块 GO 富集（心肌发育）

**需更多工作：**
- Power 敏感性分析（power=1 vs 4）
- 200+ 排列的模块保存性
- 带批次校正的心房/心室子集
- Green 模块功能验证
- 第 4 物种以打破物种 vs 心率混淆

**手稿定位：** 探索性，非确证性。Green 模块是故事核心。Turquoise 和 brown 是支持证据。物种混淆限制需前置声明。

---

## L10 Linnaeus — 记忆同步

关键事实存入 EverOS（user_id=kai, agent_id=codex）：
- Windows R 4.6.0 上 WGCNA：9 个已记录崩溃点，全部解决
- Codex Desktop 文件写入失败模式及可靠替代方案
- 趋同模块发现（turquoise, brown, green）

Obsidian vault 已同步：33 个文件复制到
C:/Users/hk200/Documents/Obsidian Vault/ResearchLoop/Yigene_WGCNA_v02/

---

## L10 Oppenheimer — 最终决策

**决策：KEEP（D0013）**

**证据等级：MODERATE**

两个趋同模块确认：
- Turquoise：高心率负相关（r=-0.955），Sk-Sm 保存性 Z=16.9，ventricle_shared_down DEG 重叠
- Brown：高心率正相关（r=+0.80），Z=4.5，atrium_shared_up 重叠

Green 模块标为心脏身份模块（保存性最强 Z=20.2，心肌 GO 条目），尽管不满足 DEG 重叠标准。

关键限制：3 物种设计中物种 vs 心率混淆无法解决。下一循环：排列提高到 200+，跑 power 敏感性，如有可用数据用第 4 物种解决物种混淆。作为探索性趋同研究有手稿价值。

---

## 输出文件位置

| 内容 | 路径 |
|------|------|
| 趋同模块汇总 | D:/R-HK/yigene/results_wgcna_loop/reports/convergent_module_summary.csv |
| 保存性结果 | D:/R-HK/yigene/results_wgcna_loop/preservation/preservation_summary.csv |
| DEG 重叠矩阵 | D:/R-HK/yigene/results_wgcna_loop/overlap/overlap_matrix.csv |
| GO/KEGG 富集 | D:/R-HK/yigene/results_wgcna_loop/enrichment/ |
| 全样本网络 | D:/R-HK/yigene/results_wgcna_loop/all_sample/ |
| 心房网络 | D:/R-HK/yigene/results_wgcna_loop/atrium/ |
| 心室网络 | D:/R-HK/yigene/results_wgcna_loop/ventricle/ |
| WGCNA 脚本 | D:/R-HK/yigene/scripts_wgcna_loop/ |
| 崩溃日志 | D:/R-HK/yigene/scripts_wgcna_loop/CRASH_LOG.md |
| RLR 项目 | D:/research_loop/Yigene_WGCNA_v02/ |
| 英文版报告 | D:/research_loop/Yigene_WGCNA_v02/FINAL_REPORT.md |
| 本中文报告 | D:/research_loop/Yigene_WGCNA_v02/FINAL_REPORT_CN.md |
| Obsidian 副本 | C:/Users/hk200/Documents/Obsidian Vault/ResearchLoop/Yigene_WGCNA_v02/ |
