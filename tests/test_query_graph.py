"""Unit test for the static composition root.

Building the graph constructs the models and toolkit but makes no network call.
"""

from __future__ import annotations


class TestBuildAgent:
    def test_module_graph_is_compiled(self):
        from northwind_copilot.query.graph import graph

        assert hasattr(graph, "astream")
        assert hasattr(graph, "invoke")

    def test_build_agent_without_openai_key(self, monkeypatch):
        # A local-only user has no OPENAI_API_KEY; the graph must still build.
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from northwind_copilot.query.graph import build_agent

        agent = build_agent()
        assert hasattr(agent, "astream")
