"""YAML frontmatter read/write helpers (Phase 3a leaf)."""
import re

from research_loop.errors import RLRError


def _yaml_value(v):
    """Render a scalar value as a safe single-line YAML string."""
    if v is None:
        v = ""
    v = str(v).replace("\n", " ").strip()
    if v == "" or re.search(r"[:#{}\[\],&*!|>'\"%@`]|^-| $", v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v

def _load_yaml_front(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]
    out = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip()
            if len(v) >= 2 and v[0] == chr(34) and v[-1] == chr(34):
                v = v[1:-1].replace(chr(92)+chr(34), chr(34)).replace(chr(92)*2, chr(92))
            out[k.strip()] = v
    return out

def _replace_field(path, key, value):
    text = path.read_text(encoding="utf-8")
    # Fail loud if the file has no YAML frontmatter: otherwise neither the regex
    # nor the "---\n" fallback below matches, and the field update is silently
    # dropped (the candidate keeps a stale status with no error). A missing
    # frontmatter means the file is corrupted -- surface it.
    if not text.startswith("---") or text.find("\n---", 4) < 0:
        raise RLRError(
            f"{path}: missing YAML frontmatter delimiters; refusing to update "
            f"'{key}' (file may be corrupted or truncated)")
    pat = re.compile(rf"^{re.escape(key)}: .*$", re.M)
    new = f"{key}: {_yaml_value(value)}"
    if pat.search(text):
        text = pat.sub(lambda m: new, text, count=1)
    else:
        text = text.replace("---\n", "---\n" + new + "\n", 1)
    path.write_text(text, encoding="utf-8")
