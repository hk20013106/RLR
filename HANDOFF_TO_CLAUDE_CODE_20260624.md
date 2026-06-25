# Handoff to Claude Code — Research Loop Room Project
## Context
Codex has run out of API quota; you are taking over the remaining work on the Research Loop Room (RLR) v0.2 framework and the active Yigene_WGCNA_v02 scientific project.
This document is stored at `D:\research_loop\HANDOFF_TO_CLAUDE_CODE_20260624.md`.

---

## Project Overview
### Core Framework: Research Loop Room v0.2
A gated multi-loop scientific council workflow for post-analysis reasoning, built to enforce explicit gates for skill discovery, project memory, input manifests, idea/method triage, evidence audit, and decision logging.
- Status: **Scaffold complete, ready for integration with Claude Code CLI**
- Core script: `D:\research_loop\research_loop_v02.py` (dependency-free, file/structure manager only)
- Documentation: `D:\research_loop\README_v0.2.md` (full specification)
- Template definitions:
  - Personas: `D:\research_loop\templates\v02_personas\` (10 named roles with clear responsibilities)
  - Layers: `D:\research_loop\templates\v02_layers\` (10 phase layers with entry/exit conditions)

### Active Scientific Project: Yigene_WGCNA_v02
**Topic:** Cross-species WGCNA: convergent co-expression modules in high heart-rate species (bat *Scotophilus kuhlii* + shrew *Suncus murinus*)
- Status: **First full loop complete, terminal status = KEEP (evidence level MODERATE)**
- Project root: `D:\research_loop\Yigene_WGCNA_v02\`
- Candidate ID: `C20260624011438577477`
- Demo project (for reference): `D:\research_loop\DemoProject_v02\` (full dummy walkthrough of all 10 personas)

---

## Completed Work (as of 2026-06-24)
### Framework (RLR v0.2)
✅ Full directory structure implemented (00_Preflight to 99_Archive)
✅ All 10 persona roles and 10 layer gates defined
✅ Core commands implemented: `new-project`, `preflight`, `new-candidate`, `note`, `route`, `triage-idea`, `triage-method`, `execution-gate`, `decision`, `obsidian-sync`, `list`, `show`
✅ Two hard gates enforced:
  - Boot Gate (L0): requires `skill_use_plan.md` and `input_manifest.md` before any work
  - Execution Gate (L7): requires preflight completion + approved method before code execution
✅ Obsidian sync implemented (links to outputs without duplication)
✅ Demo walkthrough complete (creates DemoProject_v02 with full decision history)
✅ v0.1 backward compatibility preserved (original `research_loop.py` untouched)

### Scientific Project (Yigene_WGCNA_v02)
✅ Preflight complete: all required manifest and plan files present in `00_Preflight/`
✅ Full 10-persona loop executed:
  1. L0 (Linnaeus): preflight passed
  2. L1 (Einstein): 7 candidate hypotheses generated
  3. L2 (Feynman): idea falsification completed
  4. L3 (Oppenheimer): candidate triage passed, 2 hypotheses selected
  5. L4 (Fisher): 3 method strategies proposed
  6. L5 (Tukey): method falsification / risk assessment completed
  7. L6 (Oppenheimer): method approved (three-network WGCNA + module preservation + gene set overlap + enrichment)
  8. L7 (Turing): all 6 execution steps run successfully (atrium WGCNA, ventricle WGCNA, Sk↔Sm module preservation, gene set overlap, GO/KEGG enrichment, convergent module summary)
  9. L8 (Curie): evidence audit completed, evidence level = MODERATE
  10. L9 (Feynman + Darwin): result falsification and biological interpretation completed
  11. L10 (Jobs + Oppenheimer + Linnaeus): final decision = KEEP, manuscript-worthy as exploratory convergence study
✅ Key results confirmed:
  - Two convergent modules identified:
    1. Turquoise: high-rate anti-correlated (r=-0.955), Sk-Sm preservation Z=16.9 (strong), overlaps with ventricle_shared_down DEG set
    2. Brown: high-rate correlated (r=+0.80), Sk-Sm preservation Z=4.5 (moderate), overlaps with atrium_shared_up DEG set
  - Green module: cardiac identity module (strongest preservation Z=20.2, enriched for cardiac muscle GO terms)
  - Caveat: species vs heart-rate confound unresolvable with current 3-species design
✅ All execution outputs stored in `Yigene_WGCNA_v02\04_Analysis_Outputs\` and raw results in `/hpcfile/home/hk/yigene/results_wgcna_loop/` on the lab server.

---

## Remaining Work (Prioritized)
### High Priority (First to Address)
1. **Yigene_WGCNA_v02 Follow-up Analyses (per final decision):**
   - [ ] Raise module preservation permutations from 50 to 200+ for publication robustness
   - [ ] Run power sensitivity analysis for WGCNA soft threshold and module size parameters
   - [ ] If a 4th high/low heart-rate species dataset becomes available, add it to the analysis to resolve the species vs heart-rate confound
   - [ ] Generate publication-ready figures for the two convergent modules (eigengene heatmaps, preservation plots, enrichment dotplots)
2. **RLR v0.2 Claude Code Integration:**
   - [ ] Implement Claude Code CLI integration for automated persona note generation and decision routing
   - [ ] Extend the Turing (Execution Engine) persona to run actual code via Claude Code instead of being a manual stub
   - [ ] Add support for automatic handoff generation between personas
   - [ ] Implement failure-stop enforcement (max 2 retries per method, handoff on repeated failure)

### Medium Priority
3. **Manuscript Drafting for Yigene_WGCNA_v02:**
   - [ ] Write the results section based on the confirmed convergent modules
   - [ ] Draft the discussion section addressing the confound caveat and future directions
   - [ ] Generate supplementary tables and figures
4. **RLR v0.2 Feature Additions:**
   - [ ] Add support for multiple candidates per project
   - [ ] Implement automatic progress tracking and status dashboard
   - [ ] Add support for linking to external datasets and references
   - [ ] Extend the Obsidian sync to include automatic backlinking between decision logs and outputs

### Low Priority
5. **Documentation & Testing:**
   - [ ] Write full usage documentation and tutorials
   - [ ] Add unit tests for all core commands
   - [ ] Migrate existing v0.1 projects to v0.2 format (optional, backward compatibility already preserved)

---

## Environment & Access
### Local Environment (Windows)
- Working directory: `D:\research_loop\`
- Python version: 3.10+ (no external dependencies required for the core RLR script)
- SSH access to lab server: `ssh myserver` (alias configured in `C:\Users\hk200\.ssh\config`, connects to 202.192.26.30:3011, user = hk)
- Lab server project path: `/hpcfile/home/hk/yigene/` (contains all raw data and execution results)
- Required skills: WGCNA, R, clusterProfiler, evolutionary biology, cross-species transcriptomics

### Rules to Follow
1. **AGENTS.md Rules:** Follow all global rules in `D:\research_loop\AGENTS.md` (included in this directory)
2. **PowerShell Hard Rules:** Use native PowerShell commands, avoid bash syntax on Windows, use here-strings for multi-line code, split complex commands into scripts
3. **File Write Rules:** Use `Set-Content` for large files, avoid piping Python code via PowerShell, switch methods after 2 consecutive failures
4. **Handoff Rules:** Store all handoff files in the relevant project's `03_Handoffs/` directory, use timestamped filenames, do not overwrite existing handoffs
5. **Git/VPN Rules:** Test proxy ports 7890/7897 before Git operations, verify global Git proxy settings match the active port, use Windows PowerShell for Git operations to avoid WSL proxy issues

---

## Key Files to Reference
| File Path | Purpose |
|-----------|---------|
| `D:\research_loop\README_v0.2.md` | Full RLR v0.2 specification |
| `D:\research_loop\research_loop_v02.py` | Core framework script |
| `D:\research_loop\Yigene_WGCNA_v02\00_Project_Index.md` | Yigene project overview |
| `D:\research_loop\Yigene_WGCNA_v02\01_Candidates\C20260624011438577477.md` | Full candidate decision history |
| `D:\research_loop\Yigene_WGCNA_v02\04_Analysis_Outputs\execution_report.md` | Complete execution results |
| `D:\research_loop\Yigene_WGCNA_v02\05_Decision_Log\final_decision_C20260624011438577477.md` | Final decision and next steps |
| `D:\research_loop\templates\v02_personas\*.md` | Persona role definitions |
| `D:\research_loop\templates\v02_layers\*.md` | Layer phase definitions |
| `D:\research_loop\AGENTS.md` | Global work rules |

---

## Next Immediate Step
Start by running `python research_loop_v02.py show Yigene_WGCNA_v02 C20260624011438577477` to get the full current status of the active candidate, then review the execution report and final decision to understand the follow-up analysis requirements.
