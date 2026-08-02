"""Migration audit for legacy L1 runs affected by conditional L2 routing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def install(migration_module) -> None:
    """Require an explicit migration resolution for legacy 1–4 hypothesis runs.

    Native v2.1 L1 submissions accept one to twelve hypotheses.  A native run
    with one to four hypotheses writes a hash-bound L2 skip receipt before L3.
    Historical v2.0 artifacts predate that routing receipt, so profile upgrade
    must retain them explicitly under their source profile rather than silently
    claiming that the new routing invariant was satisfied.
    """
    if getattr(migration_module, "_ROUTING_MIGRATION_COMPAT_INSTALLED", False):
        return

    original = migration_module._profile_upgrade_findings

    def _profile_upgrade_findings(
        project: Path, con, project_id: str
    ) -> list[dict[str, Any]]:
        findings = original(project, con, project_id)
        existing = {
            (str(item.get("node")), str(item.get("delta_hash")))
            for item in findings
        }
        rows = con.execute(
            "SELECT m.delta_hash,m.delta_path "
            "FROM emissions m JOIN committed_emissions c "
            "ON c.delta_hash=m.delta_hash "
            "WHERE m.project_id=? AND m.node='L1' ORDER BY m.commit_seq",
            (project_id,),
        ).fetchall()
        for row in rows:
            delta_hash = str(row["delta_hash"])
            if ("L1", delta_hash) in existing:
                continue
            artifact = project / Path(str(row["delta_path"]))
            try:
                delta = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            hypotheses = delta.get("hypotheses")
            if delta.get("schema_version") != "2.0" or not isinstance(hypotheses, list):
                continue
            if not 1 <= len(hypotheses) <= 4:
                continue
            material = {
                "kind": "STRUCTURING_REQUIRED",
                "node": "L1",
                "delta_hash": delta_hash,
                "artifact_path": Path(str(row["delta_path"])).as_posix(),
                "issues": [
                    "legacy 1–4 hypothesis run predates the hash-bound L2 skip receipt"
                ],
            }
            findings.append({
                "finding_id": f"PF:{migration_module.content_hash(material)}",
                **material,
            })
        return findings

    migration_module._profile_upgrade_findings = _profile_upgrade_findings
    migration_module._ROUTING_MIGRATION_COMPAT_INSTALLED = True
