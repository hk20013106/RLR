from pathlib import Path
from types import SimpleNamespace

import pytest

from rlr_maintenance.workspace import GitWorkspace, GitWorkspaceError


class GitFake:
    def __init__(self):
        self.base = "a" * 40
        self.committed = False
        self.calls = []

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append(command)
        args = command[1:]
        if args[:2] == ["rev-parse", "--verify"]:
            return SimpleNamespace(returncode=0, stdout=self.base + "\n", stderr="")
        if args[:3] == ["show-ref", "--verify", "--quiet"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if args[:2] == ["worktree", "add"]:
            Path(args[-2]).mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            sha = "b" * 40 if self.committed else self.base
            return SimpleNamespace(returncode=0, stdout=sha + "\n", stderr="")
        if args[:2] == ["diff", "--name-only"]:
            return SimpleNamespace(returncode=0, stdout="src/a.py\n", stderr="")
        if args[:3] == ["ls-files", "--others", "--exclude-standard"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:3] == ["diff", "--cached", "--name-only"]:
            return SimpleNamespace(returncode=0, stdout="src/a.py\n", stderr="")
        if args and args[0] == "commit":
            self.committed = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_worktree_uses_event_revision_and_host_commits_verified_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = GitFake()
    manager = GitWorkspace(repo_root=repo, workspace_parent=tmp_path / "worktrees", runner=fake)
    work = manager.create(base_revision="event-revision", event_token="abc123", todo_id="todo_event")
    assert work.base_sha == "a" * 40
    assert next(call for call in fake.calls if call[1:3] == ["worktree", "add"])[-1] == "a" * 40
    inspection = manager.inspect(work)
    assert inspection.changed_paths == ("src/a.py",)
    assert manager.commit_verified(work, changed_paths=inspection.changed_paths, message="fix: bounded repair") == "b" * 40


def test_preexisting_worktree_identity_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = GitFake()
    manager = GitWorkspace(repo_root=repo, workspace_parent=tmp_path / "worktrees", runner=fake)
    _, dirname = manager._identity("abc123", "todo_event")
    (tmp_path / "worktrees" / dirname).mkdir(parents=True)
    with pytest.raises(GitWorkspaceError, match="already exists"):
        manager.create(base_revision="event-revision", event_token="abc123", todo_id="todo_event")
