"""Runner configuration parsing and canonical per-node provider selection."""

import json
from pathlib import Path

from research_loop.providers.base import ProviderError


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
    """Parse the restricted YAML subset used by rlr_runner.yaml.

    The supported subset is nested maps plus scalar values, with no flow
    collections or lists. It is sufficient for the generated default config
    when PyYAML is unavailable.
    """

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
            child = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(val)
    return root


def load_config(path):
    """Load a YAML or JSON runner config into a dictionary."""

    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"config is invalid JSON: {exc}") from exc
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        return _mini_yaml(text)


class ProviderConfig:
    """Runner config with one canonical per-node provider resolver.

    Historical top-level ``mode`` values are retained as inert input so the
    runner can reject ``main_agent`` explicitly and warn for other values.
    Provider execution is selected only by ``provider.default`` plus an
    optional ``provider.nodes.<node>`` override.
    """

    def __init__(self, data=None, *, source_path=None):
        self.data = data or {}
        self.mode = self.data.get("mode")
        self.max_rounds = self.data.get("max_rounds", 3)
        # Compatibility-only views for callers that inspect old configs. They
        # no longer participate in provider or command resolution.
        self.main_agent = self.data.get("main_agent", {}) or {}
        self.headless = self.data.get("headless", {}) or {}
        self.manual = self.data.get("manual", {}) or {}
        provider = self.data.get("provider", {}) or {}
        self.default = provider.get("default", {"type": "headless"})
        self.nodes = provider.get("nodes", {}) or {}
        self.timeout = self.data.get("timeout")
        self.review = self.data.get("review", {"enabled": True}) or {"enabled": True}
        self.stop_policy = self.data.get("stop_policy", {}) or {}
        self.source_path = str(Path(source_path).resolve()) if source_path else None

    def for_node(self, node):
        spec = dict(self.default)
        spec.update(self.nodes.get(node, {}) or {})
        return spec

    @classmethod
    def load(cls, path):
        if path and Path(path).exists():
            return cls(load_config(path), source_path=path)
        return cls({})


__all__ = ["_scalar", "_mini_yaml", "load_config", "ProviderConfig"]
