# -*- coding: utf-8 -*-
"""L7 analysis scripts (validate_ortholog_inputs / analyze_col6a1_concordance /
analyze_ecm_ranked_program): fixture-based execution + fail-closed tests.

Uses a small SYNTHETIC workspace (not the real Yigene_Enhancer_v04 data) so
tests are fast and never touch D:/R-HK paths. Confirms:
  1. valid fixture -> all 3 scripts succeed (exit 0), write real results, and
     resolve paths workspace-locally (proven by running from an unrelated cwd)
  2. missing required input -> validate_ortholog_inputs.py fails closed (exit 1)
  3. ambiguous COL6A1 mapping -> S1 decision=STOP; S2 writes STOPPED, no
     fabricated per-contrast statistics
  4. a script named in the L6 analysis_plan but absent from disk is reported
     as missing by _approved_execution_scripts (not silently skipped) --
     regression for the original L7 blocker (missing scripts went undetected)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS_SRC = HERE / "Yigene_Enhancer_v04" / "04_Analysis_Outputs"
ENH_HEADER = ("Region\tChrom\tStart\tStop\tNumber\tSize\tXIp\tYIp\tXIn\tYIn\t"
             "Signal\tOverlap\tProximal\tClosest\tRank\tIsSuper\n")


def _enh_row(region, closest, signal, rank):
    return f"{region}\tChr1\t1\t100\t1\t100\t1\t1\t1\t1\t{signal}\t\t{closest}\t{closest}\t{rank}\t0\n"


def _deg_row(sym, logfc, adjp, t=-5.0):
    return (f'"{sym}",{logfc},1.0,{t},0.0001,{adjp},10,"{sym}",100,'
           f'"ENSSKUG1",100,"gene-{sym}",100,1.0,"pass"\n')


def _make_fixture_workspace(tmp, col6a1_ambiguous=False):
    ws = Path(tmp) / "ws"
    inputs, scripts_dir, results = ws / "inputs", ws / "scripts", ws / "results"
    for d in (inputs, scripts_dir, results):
        d.mkdir(parents=True, exist_ok=True)

    for name in ("validate_ortholog_inputs.py", "analyze_col6a1_concordance.py",
                "analyze_ecm_ranked_program.py"):
        (scripts_dir / name).write_text(
            (SCRIPTS_SRC / name).read_text(encoding="utf-8"), encoding="utf-8")

    for sp in ("Rn", "Sk", "Sm"):
        d = inputs / "enhancer_per_species" / sp
        d.mkdir(parents=True, exist_ok=True)
        rows = (ENH_HEADER + _enh_row(f"{sp}_p1", "COL6A1", 100, 5)
                + _enh_row(f"{sp}_p2", "LOX", 80, 10))
        (d / "enhancer_genes.xls").write_text(rows, encoding="utf-8")

    deg_dir = inputs / "gemini_out_chamber_species_deg_length_aware" / "results"
    deg_dir.mkdir(parents=True, exist_ok=True)
    header = ('"gene_symbol","logFC","AveExpr","t","P.Value","adj.P.Val","B",'
              '"Rnor_gene_id","Rn_length","Skuh_gene_id","Sk_length",'
              '"Smur_gene_id","Sm_length","length_ratio","qc_flag"\n')
    for contrast in ("SkV_vs_RnV", "SmV_vs_RnV"):
        lines = header
        if col6a1_ambiguous:
            lines += (_deg_row("COL6A1", -2.0, 0.01)
                     + _deg_row("COL6A1", -1.0, 0.02))  # duplicate -> ambiguous
        else:
            lines += _deg_row("COL6A1", -2.0, 0.01)
        lines += (_deg_row("LOX", 1.5, 0.03) + _deg_row("LOXL1", 1.2, 0.2)
                 + _deg_row("OTHER1", 0.1, 0.9))
        (deg_dir / f"DEG_{contrast}_all_genes.csv").write_text(lines, encoding="utf-8")

    manifest = {"workspace": str(ws.resolve()), "candidate_id": "CFIXTURE",
               "node": "L7", "staged_files": [], "missing": []}
    (ws / "WORKSPACE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return ws


def _run_script(ws, name, cwd):
    script = ws / "scripts" / name
    return subprocess.run([sys.executable, str(script)], cwd=cwd,
                          capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")


# 1. valid fixture: all three scripts succeed; run from an unrelated cwd to
#    prove path resolution is workspace-local, not cwd-based.
def test_valid_fixture_all_scripts_succeed_from_unrelated_cwd():
    with tempfile.TemporaryDirectory() as tmp:
        ws = _make_fixture_workspace(tmp)
        other_cwd = tempfile.mkdtemp()

        r1 = _run_script(ws, "validate_ortholog_inputs.py", other_cwd)
        assert r1.returncode == 0, r1.stderr
        report = json.loads((ws / "results" / "input_validation_report.json")
                            .read_text(encoding="utf-8"))
        assert report["decision"] == "PROCEED", report
        assert report["col6a1"]["overall_status"] == "comparable"

        r2 = _run_script(ws, "analyze_col6a1_concordance.py", other_cwd)
        assert r2.returncode == 0, r2.stderr
        c = json.loads((ws / "results" / "col6a1_concordance.json")
                       .read_text(encoding="utf-8"))
        assert c["status"] == "PROCEED"
        assert c["concordant_direction"] is True  # both DOWN, both significant

        r3 = _run_script(ws, "analyze_ecm_ranked_program.py", other_cwd)
        assert r3.returncode == 0, r3.stderr
        summary = json.loads((ws / "results" / "analysis_summary.json")
                             .read_text(encoding="utf-8"))
        assert summary["status"] == "OK"


# 2. missing required input -> validate script fails closed
def test_missing_deg_input_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        ws = _make_fixture_workspace(tmp)
        deg = (ws / "inputs" / "gemini_out_chamber_species_deg_length_aware"
              / "results" / "DEG_SkV_vs_RnV_all_genes.csv")
        deg.unlink()
        r = _run_script(ws, "validate_ortholog_inputs.py", str(ws))
        assert r.returncode == 1, r.stdout + r.stderr
        report = json.loads((ws / "results" / "input_validation_report.json")
                            .read_text(encoding="utf-8"))
        assert report["status"] == "FAIL"


# 3. ambiguous COL6A1 -> S1 STOP, S2 refuses (no fabricated stats)
def test_ambiguous_col6a1_stops_s2():
    with tempfile.TemporaryDirectory() as tmp:
        ws = _make_fixture_workspace(tmp, col6a1_ambiguous=True)
        r1 = _run_script(ws, "validate_ortholog_inputs.py", str(ws))
        assert r1.returncode == 0, r1.stderr
        report = json.loads((ws / "results" / "input_validation_report.json")
                            .read_text(encoding="utf-8"))
        assert report["decision"] == "STOP"
        assert report["col6a1"]["stop_gene_specific"] is True

        r2 = _run_script(ws, "analyze_col6a1_concordance.py", str(ws))
        assert r2.returncode == 0, r2.stderr
        c = json.loads((ws / "results" / "col6a1_concordance.json")
                       .read_text(encoding="utf-8"))
        assert c["status"] == "STOPPED"
        assert "contrasts" not in c  # no fabricated per-contrast stats


# 4. a script the L6 plan names but that is absent from disk is reported as
#    missing, not silently skipped -- regression for the original L7 blocker.
def test_approved_execution_scripts_reports_missing():
    sys.path.insert(0, str(HERE))
    import research_loop_v04 as rl
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        agent_notes = project / "02_Agent_Notes" / "Oppenheimer"
        agent_notes.mkdir(parents=True)
        (agent_notes / "C1_L6_oppenheimer_delta.json").write_text(
            json.dumps({"candidate_id": "C1",
                       "analysis_plan": {"scripts": ["does_not_exist.py"]}}),
            encoding="utf-8")
        resolved, missing = rl._approved_execution_scripts(str(project), "C1")
        assert resolved == []
        assert any("does_not_exist.py" in m for m in missing), missing


def _run_as_script():
    if not SCRIPTS_SRC.exists():
        # Yigene_Enhancer_v04 is project-instance data (gitignored -- "keep on
        # disk, out of repo"), like every other per-project directory. On a
        # fresh clone these scripts don't exist; skip rather than fail closed
        # on an absent fixture source (nothing to test, not a broken test).
        print(f"SKIP: {SCRIPTS_SRC} not present (project-instance data, "
              "gitignored) -- nothing to test")
        return 0
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
