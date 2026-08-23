from pathlib import Path
from types import SimpleNamespace

import pytest

from rlr_maintenance.bounded_process import BoundedProcessResult
from rlr_maintenance.workspace import GitWorkspace, GitWorkspaceError, RepairWorkspace


class GitFake:
    def __init__(self):
        self.base = "a" * 40
        self.committed = False
        self.branch = "meta-rlr/abc123-9fafe5188c01"
        self.calls = []
        self.include_receipt = False

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
        if args == ["rev-parse", "HEAD^"]:
            return SimpleNamespace(returncode=0, stdout=self.base + "\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout=self.branch + "\n", stderr="")
        if args[:2] == ["rev-list", "--count"]:
            return SimpleNamespace(returncode=0, stdout="1\n", stderr="")
        if args[:3] == ["show", "-s", "--format=%B"]:
            body = (
                "fix: bounded repair\n\n"
                "Meta-RLR-Repair-Key: abc123\n"
                "Meta-RLR-Event-ID: rme-1234567890abcdef1234\n"
                "Meta-RLR-Todo-ID: todo_event\n"
                "Meta-RLR-Turn-ID: meta-rlr:recover123\n"
                "Meta-RLR-Profile-ID: l0_state_integrity\n"
            )
            return SimpleNamespace(returncode=0, stdout=body, stderr="")
        if args[:2] == ["diff", "--name-only"]:
            if args[-1] == "HEAD":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="src/a.py\n", stderr="")
        if args[:3] == ["ls-files", "--others", "--exclude-standard"]:
            output = "verification_receipt.json\n" if self.include_receipt else ""
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
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
    assert manager.commit_verified(
        work,
        changed_paths=inspection.changed_paths,
        message="fix: bounded repair",
        event_id="rme-1234567890abcdef1234",
        todo_id="todo_event",
        turn_instance_id="meta-rlr:recover123",
        profile_id="l0_state_integrity",
    ) == "b" * 40
    commit_call = next(call for call in fake.calls if call[1] == "commit")
    commit_text = "\n".join(commit_call)
    assert "Meta-RLR-Repair-Key: abc123" in commit_text
    assert "Meta-RLR-Event-ID: rme-1234567890abcdef1234" in commit_text
    assert "Meta-RLR-Todo-ID: todo_event" in commit_text
    assert "Meta-RLR-Turn-ID: meta-rlr:recover123" in commit_text
    assert "Meta-RLR-Profile-ID: l0_state_integrity" in commit_text


def test_preexisting_worktree_identity_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = GitFake()
    manager = GitWorkspace(repo_root=repo, workspace_parent=tmp_path / "worktrees", runner=fake)
    _, dirname = manager._identity("abc123", "todo_event")
    (tmp_path / "worktrees" / dirname).mkdir(parents=True)
    with pytest.raises(GitWorkspaceError, match="already exists"):
        manager.create(base_revision="event-revision", event_token="abc123", todo_id="todo_event")


def test_existing_verified_commit_recovers_public_binding(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = GitFake()
    fake.committed = True
    manager = GitWorkspace(repo_root=repo, workspace_parent=tmp_path / "worktrees", runner=fake)
    branch, dirname = manager._identity("abc123", "todo_event")
    fake.branch = branch
    (tmp_path / "worktrees" / dirname).mkdir(parents=True)

    work = manager.find_existing(base_revision="event-revision", repair_key="abc123")
    assert work is not None
    binding = manager.read_verified_commit(work)
    assert binding.commit_sha == "b" * 40
    assert binding.base_sha == "a" * 40
    assert binding.changed_paths == ("src/a.py",)
    assert binding.repair_key == "abc123"
    assert binding.todo_id == "todo_event"
    assert binding.turn_instance_id == "meta-rlr:recover123"
    assert binding.profile_id == "l0_state_integrity"


def test_git_run_boundary_times_out_fail_closed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    manager = GitWorkspace(
        repo_root=repo,
        workspace_parent=tmp_path / "worktrees",
        runner=lambda *args, **kwargs: BoundedProcessResult(
            returncode=0,
            terminal_state="timed_out",
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_bytes=0,
            stderr_bytes=0,
            timeout_seconds=0.2,
            process_tree_cleanup={},
        ),
    )

    with pytest.raises(GitWorkspaceError, match="timed out"):
        manager._run(repo, ["status"])


def test_durable_verification_receipt_is_not_repair_code_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = GitFake()
    fake.include_receipt = True
    manager = GitWorkspace(repo_root=repo, workspace_parent=tmp_path / "worktrees", runner=fake)
    work = RepairWorkspace(
        path=tmp_path / "worktree",
        branch="meta-rlr/abc123-9fafe5188c01",
        base_sha="a" * 40,
        repair_key="abc123",
    )

    inspection = manager.inspect(work)

    assert inspection.changed_paths == ("src/a.py",)
    assert "verification_receipt.json" not in inspection.dirty_paths
