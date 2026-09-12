"""Regression tests for the PaperQA2 bridge's strict UTF-8 boundary."""

import importlib.util
import json
from pathlib import Path


def _bridge_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "paperqa2_rlr_bridge.py"
    spec = importlib.util.spec_from_file_location("paperqa2_rlr_bridge", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bridge_drops_lone_surrogate_before_strict_json_transport():
    bridge = _bridge_module()

    assert bridge._utf8_transport_text("valid UTF-8") == "valid UTF-8"
    assert bridge._utf8_transport_text("bad\ud800hit") is None

    safe = bridge._utf8_transport_text("valid UTF-8")
    encoded = json.dumps({"text": safe}, ensure_ascii=False).encode("utf-8")
    assert encoded == b'{"text": "valid UTF-8"}'
