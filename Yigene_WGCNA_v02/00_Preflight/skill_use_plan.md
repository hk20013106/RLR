# Skill Use Plan (Linnaeus L0)

Project: Yigene_WGCNA_v02
Date: 2026-06-24
Persona: Linnaeus | Catalog Master

## AGENTS.md

Read and active: D:/research_loop/AGENTS.md (inherited from workspace root).
Key rules: PowerShell-first, no bash-in-PowerShell, here-strings for multiline,
check skills_inventory before complex tasks, verify before reporting.

## Skills Inventory Checked

Source: D:/skills/skills_inventory.md (93 filesystem skills, 11 plugin capabilities)

### Relevant Skills Found

1. **bat-heart-target-screen** (C:/Users/hk200/.codex/skills/bat-heart-target-screen/SKILL.md)
   - Directly targets D:/R-HK/yigene bat heart RNA-seq workflow
   - Contains provenance rules, excluded-sample lists, server access patterns
   - Relevant for: sample provenance verification, CACNA1S/CaV/RyR expression checks
   - USE FOR: verifying sample metadata, confirming species assignments

2. **bulk-rnaseq** (C:/Users/hk200/.codex/skills/bulk-rnaseq/SKILL.md)
   - End-to-end bulk RNA-seq orchestrator (FastQC -> STAR/Salmon -> counts -> DE -> enrichment)
   - Relevant for: TMM normalization, voom, counts matrix handling
   - USE FOR: confirming normalization approach is sound, enrichment stage

3. **karpathy-guidelines** (C:/Users/hk200/.codex/skills/karpathy-guidelines/SKILL.md)
   - Behavioral guidelines: think before coding, simplicity first, surgical changes
   - USE FOR: before any script writing in Turing phase

4. **systematic-debugging** (C:/Users/hk200/.codex/skills/systematic-debugging/SKILL.md)
   - Use when encountering bugs, test failures, unexpected behavior
   - USE FOR: if WGCNA scripts crash again (prevents infinite retry loops)

5. **academic-research-suite** (C:/Users/hk200/.codex/skills/academic-research-suite/SKILL.md)
   - Literature search and deep research capabilities
   - USE FOR: Einstein (L1) hypothesis generation, Darwin (L9) biology interpretation

6. **everos-memory** (C:/Users/hk200/.codex/skills/everos-memory/SKILL.md)
   - Local-first memory OS at http://127.0.0.1:9000, user_id=kai
   - USE FOR: project memory sync, cross-tool durable facts
   - Status: ONLINE (verified 2026-06-24)

### Skills NOT Found (Gaps)

- No dedicated WGCNA skill exists locally. WGCNA R scripts must be written from scratch
  but should follow patterns from the v0.1 crash log (D:/R-HK/yigene/scripts_wgcna_loop/CRASH_LOG.md)
- No dedicated cross-species co-expression analysis skill
- No Obsidian vault integration skill (vault paths found but no active vault for this project)

### Skill Use Plan

| Phase | Persona | Skill | Action |
|-------|---------|-------|--------|
| L0 | Linnaeus | bat-heart-target-screen | Verify sample provenance and species assignments |
| L1 | Einstein | academic-research-suite | Literature on convergent heart-rate evolution, co-expression modules |
| L4 | Fisher | bulk-rnaseq | Confirm TMM+voom normalization is appropriate for cross-species WGCNA |
| L5 | Tukey | systematic-debugging | Review CRASH_LOG.md for known WGCNA-on-Windows failure modes |
| L7 | Turing | karpathy-guidelines | Think before coding, split scripts into modular steps |
| L9 | Darwin | academic-research-suite | Biological interpretation of modules, literature support |
