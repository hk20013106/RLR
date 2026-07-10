"""HeadlessProvider: external AI CLI provider, one fresh subprocess per node (Phase 4)."""
import os

from research_loop.providers.base import (
    AgentProvider, ProviderError, _run_command_agent,
)


class HeadlessProvider(AgentProvider):
    """Headless-command-mode provider: invokes an external AI CLI / wrapper
    headlessly, once per node (a fresh subprocess = fresh session). This is
    Python automatically calling an external AI -- it is NOT the current live
    chat session (Python cannot drive that). The command is resolved, in order,
    from: spec['command']; $RLR_HEADLESS_CMD (or legacy $RLR_HOST_AGENT_CMD);
    best-effort detection. If none resolves it raises ProviderError -- it NEVER
    falls back to manual.
    """

    type = "headless"

    def __init__(self, spec=None):
        self.spec = spec or {}
        self.name = "headless"
        self.timeout = self.spec.get("timeout")
        self.last_prompt_file = None
        self.last_delta_file = None
        self.last_fresh_session = True
        self.command = (self.spec.get("command")
                        or os.environ.get("RLR_HEADLESS_CMD")
                        or os.environ.get("RLR_HOST_AGENT_CMD")
                        or self._detect())
        if not self.command:
            raise ProviderError(
                "headless mode could not resolve a command. Set $RLR_HEADLESS_CMD "
                "to a headless command template (it MUST write the delta JSON to "
                "{output_file}), e.g.\n"
                "  export RLR_HEADLESS_CMD='claude -p < {prompt_file} > {output_file}'\n"
                "or set headless.command in rlr_runner.yaml. "
                "(For interactive use prefer main-agent mode; manual is debug-only.)")

    @staticmethod
    def _detect():
        env = os.environ
        if env.get("CLAUDECODE") or env.get("CLAUDE_CODE"):
            return "claude -p < {prompt_file} > {output_file}"
        return None

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        return _run_command_agent(self.command, node, persona, context,
                                  output_schema, workspace, tools, run_dir,
                                  self.timeout, self)
