# 最终报告: Convergent co-expression modules in high heart-rate species (bat + shrew)

**候选编号:** C20260625114729640306
**状态:** KEEP
**生成时间:** 2026-06-25T15:25:59
**框架:** RLR v0.3.0

## 科学问题

Sk (Scotophilus kuhlii, bat) and Sm (Suncus murinus, shrew) independently evolved high heart rates. Do they share co-expression modules in atrium and/or ventricle that represent convergent molecular signatures of cardiac adaptation, absent in the low-rate rat (Rattus norvegicus)?

## 主张

High heart-rate species Sk and Sm share co-expression modules in atrium and/or ventricle that are not present in the low-rate rat Rn. These modules represent convergent molecular signatures of cardiac adaptation.

## L0 - 预检 (Linnaeus)

**发现的技能：** bat-heart-target-screen, bulk-rnaseq, systematic-debugging, academic-research-suite
**技能缺口：** 无专用 WGCNA 技能；基于 v0.1 崩溃日志模式从零编写脚本
**输入校验：** expression_matrix=11974 基因 x 71 样本 (length_scaled_counts.csv); sample_metadata=过滤后 71 样本 (sample_metadata_corrected.csv); sample_breakdown=Rn=24 (8A+16V), Sk=23 (7A+16V), Sm=24 (8A+16V); deg_gene_sets=gene_sets/ 下 20 个文件; gene_mapping=11648 行 (rat_symbol -> mouse_entrez); wgcna_results=all_sample, atrium, ventricle, preservation, overlap, enrichment, reports 目录已验证
**环境：** python=3.13; r_version=4.6.0 (D:/Programs/R/R-4.6.0/bin/Rscript.exe); r_library=D:/R-HK/Seurat5_lib (798 包); everos=在线 (http://127.0.0.1:9000); obsidian_vault=C:/Users/hk200/Documents/Obsidian Vault
**技能使用计划：** bat-heart-target-screen: 样本来源验证, bulk-rnaseq: TMM/voom 标准化方法确认, systematic-debugging: WGCNA 崩溃预防 (CRASH_LOG.md, 9 个崩溃点), academic-research-suite: 假设生成的文献支持与生物学解释
**禁止的捷径：** R 脚本中禁止 sink(), 禁止多线程 WGCNA (nThreads=1, disableWGCNAThreads), 禁止对大文件或含特殊字符的 JSON 使用 apply_patch, 禁止通过 PowerShell 管道传递 Python 代码, 禁止 os.link (使用 shutil.copy2)


## L1 - 假说生成 (Einstein)

- **H1:** Sk 和 Sm 共享心房趋同共表达模块，在 Rn 中不存在 (可检验=True)
  - 推理： 心房 n=23 处于边界但可检验；Sk 心房仅 7 个样本，统计效力有限
- **H2:** Sk 和 Sm 共享心室趋同共表达模块，在 Rn 中不存在 (可检验=True)
  - 推理： 心室 n=48 样本量充足，是最强可检验假设
- **H3:** Sk 和 Sm 共享全心趋同签名 (可检验=False)
  - 推理： 不区分腔室则太宽泛，无法定位信号来源
- **H4:** 共享模块富集能量代谢通路 (可检验=True)
  - 推理： 高心率需要高 ATP 供给，但需 GO/KEGG 验证
- **H5:** 共享模块富集钙离子处理基因 (可检验=True)
  - 推理： 钙循环是心率调控核心，但需 GO/KEGG 验证
- **H6:** 共享模块富集 ECM/结构重塑基因 (可检验=True)
  - 推理： 心肌重塑可能伴随高心率适应，但需 GO/KEGG 验证
- **H7:** 零假设：无趋同模块 (可检验=True)
  - 推理： 可通过保存性 Z < 2 检验

**主假说：** H2
**关键不确定性：** 全样本 WGCNA（第一轮）发现物种特异性模块（turquoise=物种, yellow=Sm, brown=Sk），但无法测试腔室特异性趋同


## L2 - 假说证伪 (Feynman)

- **[HIGH]** H1: 心房样本量不足：Sk 心房仅 7 个样本，n=23 的 WGCNA 处于边界，模块稳定性存疑
- **[MEDIUM]** H2: 批次混淆：batch1=59, batch2=12，需验证批次与物种不混淆
- **[MEDIUM]** H1: 无符号网络：上调和下调基因合并到同一模块，共享模块可能是基因方向相反的假象
- **[LOW]** H2: 强制 power=4：自动选择为 1，强制 4 可能制造人工结构
- **[MEDIUM]** H2: 动物伪重复：12 个 animal_id 跨 71 个样本，配对设计非完全独立

**混杂因素：**
- [MEDIUM] 批次效应: batch1=59, batch2=12，子集无法包含批次协变量
- [HIGH] 物种 vs 心率混淆: 三物种设计中物种与心率完全混淆，无法分离

**诊断性检验：**
- table(species, chamber, batch): 检查批次与物种/腔室的混淆
- 模块保存性 Zsummary: Sk vs Sm 保存性检验
- signed network 对比: 验证 unsigned 模块是否为假象

**裁决：** H2（心室趋同）是最强可检验假设。H1（心房）应尝试但可能因样本量失败。H7（零假设）必须同时报告。


## L3 - 候选筛选 (Oppenheimer)

**已选中：** H1, H2, H7
**已否决：** H3, H4, H5, H6
**理由：** H1（心房趋同）和 H2（心室趋同）可用现有数据检验。H7（零假设）是证伪基线。H3 过于宽泛，H4/H5/H6 需要 GO/KEGG 结果才能检验，作为后续步骤。
**路由至：** Fisher


## L4 - 方案设计 (Fisher)

- **A: 三网络 WGCNA + 模块保存性** (样本数=71, 状态=部分完成（全样本已跑）)
  - 步骤： 全样本网络, 心房网络, 心室网络, Sk vs Sm 保存性, 模块-性状相关
- **B: 基因集重叠 (Fisher exact)** (样本数=0, 状态=新增)
  - 步骤： 模块基因 vs DEG 共享集, 108 个 Fisher 检验
- **C: GO/KEGG 富集** (样本数=0, 状态=新增)
  - 步骤： 每个模块 enrichGO (BP/MF/CC), enrichKEGG (mmu)

**推荐方案：** A+B+C 全部执行

**所需脚本：**
- 02_run_wgcna_atrium.R: 心房 WGCNA (n=23) (状态=待执行)
- 03_run_wgcna_ventricle.R: 心室 WGCNA (n=48) (状态=待执行)
- 04_module_preservation.R: Sk vs Sm 模块保存性 (状态=待执行)
- 05_gene_set_overlap.R: 模块 vs DEG Fisher 检验 (状态=待执行)
- 06_go_kegg_enrichment.R: GO/KEGG 富集 (状态=待执行)
- 07_convergent_module_summary.R: 趋同模块汇总 (状态=待执行)

**关键决策：** unsigned 网络, power=4, top-5000 MAD 基因, minModuleSize=30, mergeCutHeight=0.25


## L5 - 方案证伪 (Tukey)

- **[HIGH]** 心房样本量: Sk 心房仅 7 样本，模块稳定性存疑
- **[MEDIUM]** 批次混淆: 子集无法包含批次协变量
- **[MEDIUM]** 无符号网络: 上调下调基因合并可能产生假模块

**质控检查点：**
- WGCNA 前检查: table(species, chamber, batch) 检查混淆
- blockwiseModules 后: 模块数 >= 3，否则停止
- 保存性后: 报告 Zsummary 值，不只是 pass/fail
- 富集后: FDR < 0.05，每 GO term 至少 5 基因

**失败停止规则：**
- 心房 0 模块: 停止，报告
- 批次与物种混淆: 停止，无法分离效应
- 无 DEG 重叠: 诚实报告零结果


## L6 - 分析计划审批 (Oppenheimer)

**批准的策略：** A+B+C（三网络 WGCNA + 保存性 + 基因集重叠 + 富集）
**修改项：** 脚本拆分为独立步骤, 每步保存 RData, 心房标记为探索性
**理由：** 策略 A+B+C 覆盖所有假设检验需求。Tukey QC 门控已接受。脚本按轮-1 教训拆分为模块化步骤。

**分析计划：**
- 脚本： 02_run_wgcna_atrium.R, 03_run_wgcna_ventricle.R, 04_module_preservation.R, 05_gene_set_overlap.R, 06_go_kegg_enrichment.R, 07_convergent_module_summary.R
- 参数： networkType=unsigned; power=4; maxBlockSize=6000; minModuleSize=30; mergeCutHeight=0.25; nThreads=1; top_genes=5000
- 输出： atrium_network.RData, ventricle_network.RData, preservation_summary.csv, overlap_matrix.csv, enrichment_summary.csv, convergent_module_summary.csv


## L7 - 执行 (Turing)

- **02_run_wgcna_atrium.R** 退出码=0
  - 输出文件： atrium_network.RData, atrium_module_assignment.csv, atrium_module_eigengenes.csv, atrium_soft_threshold.pdf
- **03_run_wgcna_ventricle.R** 退出码=0
  - 输出文件： ventricle_network.RData, ventricle_module_assignment.csv, ventricle_module_eigengenes.csv, ventricle_soft_threshold.pdf
- **04_module_preservation.R** 退出码=0
  - 输出文件： module_preservation.RData, preservation_summary.csv, Sk_ref_Sm_test_preservation.csv, Sm_ref_Sk_test_preservation.csv
- **05_gene_set_overlap.R** 退出码=0
  - 输出文件： overlap_matrix.csv
- **06_go_kegg_enrichment.R** 退出码=0
  - 输出文件： enrichment_summary.csv, green_GO_BP.csv, green_GO_MF.csv, green_KEGG.csv
- **07_convergent_module_summary.R** 退出码=0
  - 输出文件： convergent_module_summary.csv

**关键结果：** atrium_modules=4 个模块; ventricle_modules=5 个模块; preservation_turquoise_Z=16.9; preservation_brown_Z=4.5; preservation_green_Z=20.2; turquoise_heart_rate_cor=-0.955; brown_heart_rate_cor=0.8; green_heart_rate_cor=-0.524; turquoise_DEG_overlap=ventricle_shared_down; brown_DEG_overlap=atrium_shared_up; enrichment_only_in=green (49 GO-BP / 15 MF / 1 KEGG)
**警告：** 心房 n=23 偏小，模块为探索性, 保存性仅 50 次排列, 大模块 ORA 统计功效不足


## L8 - 证据审查 (Curie)

- atrium_module_assignment.csv: 模块基因数总和 = 5000 基因，正确
- ventricle_module_assignment.csv: 模块基因数总和 = 5000 基因，正确
- preservation_summary.csv: Zsummary 值 = turquoise Z=16.9, brown Z=4.5, green Z=20.2，与报告一致
- overlap_matrix.csv: Fisher p 值 = 108 检验，turquoise 和 brown 显著重叠
- enrichment_summary.csv: GO/KEGG 结果 = 仅 green 模块有显著富集（宇宙效应）

**证据级别：** MODERATE
**注意事项：** 心房 n=23 偏小，结果为探索性, 保存性仅 50 次排列（需提至 200+）, GO/KEGG 仅 green 模块显著（大模块统计功效不足）, 物种 vs 心率混淆无法解决


## L9a - 结果证伪 (Feynman)

- **[HIGH]** 物种 vs 心率混淆 (可解决=False): 三物种设计中物种与心率完全混淆，无法分离趋同信号与物种特异性信号。需第四物种解决。
- **[MEDIUM]** 无符号网络假象 (可解决=True): turquoise 模块可能合并了上调和下调基因。signed network 可验证。
- **[HIGH]** 心房样本量不足 (可解决=False): Sk 心房仅 7 样本，心房模块稳定性无法保证。
- **[LOW]** 保存性排列次数不足 (可解决=True): 50 次排列，p 值不稳定。提至 200+ 可解决。

**通过项：** turquoise 趋同信号（保存性 Z=16.9 极强）, brown 趋同信号（Z=4.5，中等）, green 心脏身份模块（Z=20.2）
**被证伪项：** H1（心房趋同）：心房样本量不足以确信模块稳定性


## L9b - 生物学解读 (Darwin)

- **turquoise:** 高心率负相关模块——可能代表低心率物种（Rn）中活跃、高心率物种中抑制的通路
  - 基因： 未列出具体 hub 基因
  - 证据： r=-0.955 与 high_heart_rate，Z=16.9 保存性，与心室 shared-down DEG 重叠
- **brown:** 高心率正相关模块——可能代表高心率物种中激活的适应性通路
  - 基因： 未列出具体 hub 基因
  - 证据： r=+0.80 与 high_heart_rate，Z=4.5 保存性，与心房 shared-up DEG 重叠
- **green:** 心脏身份模块——保存性最强，富集心肌相关 GO terms
  - 基因： 未列出具体 hub 基因
  - 证据： Z=20.2 保存性，49 GO-BP / 15 MF / 1 KEGG 富集，但未通过 DEG 重叠标准

**趋同进化：** turquoise 和 brown 模块满足趋同三标准（高心率相关 + Sk-Sm 保存性 + DEG 重叠），支持 Sk 和 Sm 独立演化出共享共表达模块的假说。但物种 vs 心率混淆是主要限制。
**局限性：** 物种 vs 心率混淆无法解决, 心房样本量不足, 保存性排列次数不足, 大模块 ORA 统计功效不足


## L10a - 价值评估 (Jobs)

**价值评估：** 作为探索性趋同研究具有发表价值。turquoise 和 brown 模块的趋同证据中等偏强，但物种混淆是审稿人必问的硬伤。
**核心结论：** 高心率蝙蝠和鼩鼱共享两个共表达模块，提示趋同分子适应

**当前可发表：** turquoise/brown 趋同模块发现, 保存性分析, DEG 重叠验证
**仍需工作：** 保存性排列提至 200+, signed network 验证, hub 基因功能验证, 物种混淆解决（第四物种）, turquoise core ORA, kME-ranked GSEA, ECM score 相关分析

**论文框架：** 定位为 exploratory convergence study，强调发现性而非确证性。在 discussion 中明确物种混淆限制，提出第四物种作为后续计划。


## L10b - 最终决策 (Oppenheimer)

**决定：** KEEP
**证据级别：** MODERATE
**理由：** 两个趋同模块确认（turquoise：与高心率负相关 r=-0.955，Sk-Sm 保存性 Z=16.9，与心室 shared-down DEG 重叠；brown：与高心率正相关 r=+0.80，Z=4.5，与心房 shared-up DEG 重叠）。Green 模块标记为心脏身份模块（保存性最强 Z=20.2，富集心肌相关 GO terms），但未通过 DEG 重叠标准。关键 caveat：三物种设计下物种 vs 心率混淆无法解决。可作为探索性趋同研究发表。

**后续步骤：**
- 保存性排列提至 200+
- power 敏感性分析
- 加第四物种解决混淆
- signed network 分析（验证 turquoise/brown 不是无符号网络假象）
- hub 基因功能验证
- 仅对 turquoise core（高 kME 基因）做 ORA，不对整个大模块做
- kME 排序 GSEA 替代仅 ORA
- ECM score 与 module eigengene 相关分析
- 生成最终报告并同步 Obsidian


---

**最终决策:** KEEP: L8-L10 review complete. Evidence level: MODERATE. Two convergent modules confirmed (turquoise: high-rate anti-correlated r=-0.955, Sk-Sm preservation Z=16.9, ventricle_shared_down DEG overlap; brown: high-rate correlated r=+0.80, Z=4.5, atrium_shared_up overlap). Green module flagged as cardiac identity module. Key caveat: species vs heart-rate confound unresolvable with 3-species design.

_报告由 RLR v0.3.0 aggregate-report (L10c Linnaeus) 生成_