#!/usr/bin/env python3
import os
import re
import sys
import json
import yaml
from pathlib import Path

def normalize_title(t):
    """Clean title for comparison: lowercase, remove non-alphanumeric."""
    if not t:
        return ""
    return re.sub(r"[^\w\s]", "", t.strip().lower())

def slugify(s):
    """Clean string for filename: lowercase, replace spaces/specials with underscores."""
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-\s]+", "_", s)[:60]

def parse_yaml_front(filepath):
    """Load frontmatter from a Markdown file."""
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) >= 3:
        try:
            fm = yaml.safe_load(parts[1]) or {}
            return fm, parts[2].strip()
        except Exception:
            return {}, text
    return {}, text

def write_yaml_front(filepath, fm, body=""):
    """Save frontmatter and body to a Markdown file."""
    fm_str = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n\n{body}"
    filepath.write_text(content, encoding="utf-8")

class LiteratureDB:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.db_dir = self.project_dir / "09_Literature_Database"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.papers = {} # key: filename, value: frontmatter dict
        self._load_all()

    def _load_all(self):
        """Scan db_dir and load all paper files."""
        for f in self.db_dir.glob("*.md"):
            if f.name == "00_Library_Index.md":
                continue
            fm, _ = parse_yaml_front(f)
            self.papers[f.name] = fm

    def find_duplicate(self, doi=None, title=None):
        """Check if paper exists by DOI or normalized Title."""
        norm_title = normalize_title(title)
        for fname, fm in self.papers.items():
            if doi and fm.get("doi") == doi:
                return fname, fm
            if norm_title and normalize_title(fm.get("title")) == norm_title:
                return fname, fm
        return None, None

    def add_or_update_paper(self, paper_data, round_id=1):
        """Add new paper or update existing paper's round and properties."""
        doi = paper_data.get("doi")
        title = paper_data.get("title")
        authors = paper_data.get("authors")
        year = paper_data.get("year")
        
        # Check duplicate
        fname, existing_fm = self.find_duplicate(doi, title)
        
        if existing_fm:
            # Update existing
            print(f"[DB] Paper already exists: {fname}. Updating fields.")
            rounds = existing_fm.get("rounds", [])
            if round_id not in rounds:
                rounds.append(round_id)
            existing_fm["rounds"] = sorted(rounds)
            
            # Update any empty fields
            for k in ["doi", "journal", "evidence_level", "url"]:
                if k in paper_data and not existing_fm.get(k):
                    existing_fm[k] = paper_data[k]
            
            # Append core arguments if not already present
            args = existing_fm.get("core_arguments", [])
            for arg in paper_data.get("core_arguments", []):
                if arg not in args:
                    args.append(arg)
            existing_fm["core_arguments"] = args
            
            # Merge tags
            tags = set(existing_fm.get("tags", [])) | set(paper_data.get("tags", []))
            existing_fm["tags"] = sorted(list(tags))
            
            _, body = parse_yaml_front(self.db_dir / fname)
            write_yaml_front(self.db_dir / fname, existing_fm, body)
            return fname
        else:
            # Create new
            first_author = "Unknown"
            if isinstance(authors, list) and len(authors) > 0:
                first_author = authors[0].split(",")[-1].split(" ")[-1].strip()
            elif isinstance(authors, str) and len(authors) > 0:
                first_author = authors.split(",")[0].split(" ")[-1].strip()
            
            first_word_title = "paper"
            if title:
                words = [w for w in title.split(" ") if w.lower() not in ["the", "a", "an", "of", "and", "in", "on", "at"]]
                if len(words) > 0:
                    first_word_title = words[0]
            
            citekey = slugify(f"{first_author}_{year or 'unknown'}_{first_word_title}")
            new_fname = f"{citekey}.md"
            
            fm = {
                "doi": doi or "",
                "title": title or "Unknown Title",
                "authors": authors or [],
                "journal": paper_data.get("journal", "Unknown Journal"),
                "year": year or "",
                "core_arguments": paper_data.get("core_arguments", []),
                "evidence_level": paper_data.get("evidence_level", "MODERATE"),
                "rounds": [round_id],
                "tags": sorted(paper_data.get("tags", [])),
                "url": paper_data.get("url", "")
            }
            
            body = f"# Summary\n\n[Auto-generated summary from literature review]\n\n"
            summary_body = paper_data.get("summary", "")
            if summary_body:
                body += summary_body + "\n"
            
            write_yaml_front(self.db_dir / new_fname, fm, body)
            self.papers[new_fname] = fm
            print(f"[DB] Added new paper: {new_fname}")
            return new_fname

    def sync_index(self):
        """Regenerate the 00_Library_Index.md master list."""
        index_file = self.db_dir / "00_Library_Index.md"
        lines = [
            "# Literature Database Index\n",
            "> Synced and growable literature database for Project.\n",
            "| Paper (Link) | Year | Journal | Evidence | Rounds | Core Arguments |",
            "| :--- | :---: | :--- | :---: | :---: | :--- |"
        ]
        
        # Sort papers by year (descending), then author
        sorted_papers = []
        for fname, fm in self.papers.items():
            sorted_papers.append((fname, fm))
        
        sorted_papers.sort(key=lambda x: (x[1].get("year") or 0, x[0]), reverse=True)
        
        for fname, fm in sorted_papers:
            title = fm.get("title", "Unknown")
            year = fm.get("year", "")
            journal = fm.get("journal", "")
            ev = fm.get("evidence_level", "MODERATE")
            rounds = ", ".join(f"R{r}" for r in fm.get("rounds", []))
            args = "; ".join(fm.get("core_arguments", []))
            
            link = f"[[09_Literature_Database/{Path(fname).stem}|{title}]]"
            lines.append(f"| {link} | {year} | {journal} | {ev} | {rounds} | {args} |")
            
        index_file.write_text("\n".join(lines), encoding="utf-8")
        print(f"[DB] Library index updated: {index_file}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Growable Literature Database Manager")
    sub = p.add_subparsers(dest="cmd")
    
    # init
    sp_init = sub.add_parser("init")
    sp_init.add_argument("project_dir")
    
    # add
    sp_add = sub.add_parser("add")
    sp_add.add_argument("project_dir")
    sp_add.add_argument("--json-data", required=True, help="CSL-JSON format or key-values of paper metadata")
    sp_add.add_argument("--round", type=int, default=1)
    
    # sync
    sp_sync = sub.add_parser("sync")
    sp_sync.add_argument("project_dir")
    
    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)
        
    db = LiteratureDB(args.project_dir)
    
    if args.cmd == "init":
        db.sync_index()
        print("[DB] Initialized.")
        
    elif args.cmd == "add":
        try:
            data = json.loads(args.json_data)
        except Exception as e:
            print(f"ERROR: invalid JSON data: {e}", file=sys.stderr)
            sys.exit(2)
        db.add_or_update_paper(data, round_id=args.round)
        db.sync_index()
        
    elif args.cmd == "sync":
        db.sync_index()
