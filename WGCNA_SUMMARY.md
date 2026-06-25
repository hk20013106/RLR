# WGCNA 结果摘要

## 核心问题

蝙蝠 (Sk, Scotophilus kuhlii) 和鼩鼱 (Sm, Suncus murinus) 独立演化出高心率。
它们是否在心房或心室共享共表达模块(趋同演化的分子签名)，而低心率的大鼠 (Rn, Rattus norvegicus) 没有？

## 物种

- Sk = 小黄蝠，高心率
- Sm = 大臭鼩，高心率
- Rn = 大鼠，低心率外群

## 数据

- 表达矩阵：11974 基因 x 71 样本
- 样本分布：Rn=24 (8心房+16心室), Sk=23 (7心房+16心室), Sm=24 (8心房+16心室)

## 结论

两个模块满足趋同三标准(高心率相关 + Sk-Sm 保存性 + DEG 重叠)：

1. turquoise 模块
   
   - 与高心率负相关 r = -0.955
   - Sk-Sm 保存性 Z = 16.9
   - 与心室共享下调基因重叠

2. brown 模块
   
   - 与高心率正相关 r = +0.80
   - Sk-Sm 保存性 Z = 4.5
   - 与心房共享上调基因重叠

证据等级：MODERATE

## 主要 caveat

- 心房样本量偏小 (n=23)，结果为探索性
- 保存性检验仅 50 次置换，需提到 200+
- 物种与心率的混淆在三物种设计中无法解决

## 结果文件位置

- R 脚本输出：D:\R-HK\yigene\results_wgcna_loop\ (atrium, ventricle, preservation, overlap, enrichment, reports)
- R 脚本：D:\R-HK\yigene\scripts_wgcna_loop\ (01-07)
- 最终报告：D:\research_loop\Yigene_WGCNA_v03\FINAL_REPORT.md
- 中文报告：D:\research_loop\Yigene_WGCNA_v03\FINAL_REPORT_CN.md
