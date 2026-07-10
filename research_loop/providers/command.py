"""CommandProvider: headless shell-command-template provider (Phase 4)."""
from research_loop.providers.base import (
    AgentProvider, ProviderError, _run_command_agent,
)


class CommandProvider(AgentProvider):
    """Automatic provider for an external headless CLI. Runs a shell command
    template once per node; the command MUST write the delta JSON to
    {output_file}. Placeholders: {prompt_file} {output_file} {node} {persona}
    {workspace}. Each node = a fresh subprocess (fresh session)."""

    type = "command"

    def __init__(self, spec):
        self.spec = spec or {}
        self.name = "command"
        self.command = self.spec.get("command")
        self.timeout = self.spec.get("timeout")
        self.last_prompt_file = None
        self.last_delta_file = None
        self.last_fresh_session = True
        if not self.command:
            raise ProviderError(
                "command provider requires a 'command' template (using "
                "{prompt_file} and {output_file})")

    def run_agent(self, node, persona, context, output_schema=None,
                  workspace=None, tools=None, run_dir=None):
        return _run_command_agent(self.command, node, persona, context,
                                  output_schema, workspace, tools, run_dir,
                                  self.timeout, self)
