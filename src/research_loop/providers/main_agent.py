"""Runner config + main-agent mode (Phase 4 leaf).

main_agent (default `ProviderConfig.mode`): the host agent IS the
orchestrator; NO python provider is constructed for it (see make_provider,
which raises for type none). This module houses the config that selects
the mode. Stdlib only -> pure leaf."""
import json
from pathlib import Path


def _scalar(v):
    s = v.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s

def _mini_yaml(text):
    """Parse the restricted YAML subset used by rlr_runner.yaml (nested maps +
    scalars; no flow collections, no lists). Sufficient for the default config
    template when PyYAML is not installed."""
    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, val = line.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            d = {}
            parent[key] = d
            stack.append((indent, d))
        else:
            parent[key] = _scalar(val)
    return root

def load_config(path):
    """Load a YAML or JSON config into a dict (PyYAML optional)."""
    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(f"config is invalid JSON: {e}") from e
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except Exception:
        return _mini_yaml(text)

class ProviderConfig:
    """Runner config. Top-level `mode` selects how nodes are executed:
      - main_agent (default): the current host agent IS the orchestrator; NO
        python provider is used (an execution protocol, not a provider).
      - headless: python calls an external AI CLI/wrapper per node.
      - manual: DEBUG-ONLY human-in-the-loop.
    """

    def __init__(self, data=None):
        self.data = data or {}
        self.mode = self.data.get("mode", "main_agent")
        self.max_rounds = self.data.get("max_rounds", 3)
        self.main_agent = self.data.get("main_agent", {}) or {}
        self.headless = self.data.get("headless", {}) or {}
        self.manual = self.data.get("manual", {}) or {}
        prov = self.data.get("provider", {}) or {}
        self.default = prov.get("default", {"type": "none"})
        self.nodes = prov.get("nodes", {}) or {}
        self.timeout = self.data.get("timeout")
        self.review = self.data.get("review", {"enabled": True}) or {"enabled": True}
        self.stop_policy = self.data.get("stop_policy", {}) or {}

    def for_node(self, node):
        spec = dict(self.default)
        spec.update(self.nodes.get(node, {}) or {})
        return spec

    @classmethod
    def load(cls, path):
        if path and Path(path).exists():
            return cls(load_config(path))
        return cls({})
