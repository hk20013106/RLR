# Research Loop Room

## v0.1 (DEPRECATED)

v0.1 was a 7-agent linear loop (Idea, Value, Evidence, Falsification, Biology,
Decision, Execution) with 9 statuses. It lacked skill discovery gates, method
triage, execution safety, and project memory integration. Deprecated in favor
of v0.2.

## v0.2 (DEPRECATED)

See README_v0.2.md and research_loop_v02.py. Superseded by v0.3. Still works;
existing v0.2 projects are untouched.

## v0.3 (current)

See README_v0.3.md, DAG_TOPOLOGY.md, and research_loop_v03.py. v0.3 converts
each persona into an independent subagent with physical context isolation via
a 14-node DAG (L0-L10c), communicating through structured delta JSON files.

Templates: templates/v03_personas/ and templates/v03_layers/.
