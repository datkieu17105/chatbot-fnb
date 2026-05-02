from __future__ import annotations

from typing import Any, Callable

from app.chatbot.nodes import BakeryChatbotNodes
from app.chatbot.state import ChatbotState


class BakeryChatbotGraph:
    def __init__(self, chatbot: Any) -> None:
        self.nodes = BakeryChatbotNodes(chatbot)
        self._compiled_graph = self._build_langgraph()

    def invoke(self, query: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        initial_state: ChatbotState = {
            "query": query,
            "history": history or [],
        }

        if self._compiled_graph is not None:
            final_state = self._compiled_graph.invoke(initial_state)
        else:
            final_state = self._invoke_without_langgraph(initial_state)

        return final_state["response"]

    def _build_langgraph(self) -> Any | None:
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        graph = StateGraph(ChatbotState)
        graph.add_node("prepare_context", self.nodes.prepare_context)
        graph.add_node("route", self.nodes.route)
        graph.add_node("conversation_guard", self.nodes.conversation_guard)
        graph.add_node("general", self.nodes.general)
        graph.add_node("scope_guard", self.nodes.scope_guard)
        graph.add_node("local_grounded", self.nodes.local_grounded)
        graph.add_node("local_curated", self.nodes.local_curated)
        graph.add_node("model_grounded", self.nodes.model_grounded)
        graph.add_node("finalize", self.nodes.finalize)

        graph.set_entry_point("prepare_context")
        graph.add_edge("prepare_context", "route")
        graph.add_conditional_edges(
            "route",
            self._next_node,
            {
                "conversation_guard": "conversation_guard",
                "general": "general",
                "scope_guard": "scope_guard",
                "local_grounded": "local_grounded",
                "local_curated": "local_curated",
                "model_grounded": "model_grounded",
            },
        )
        for node_name in (
            "conversation_guard",
            "general",
            "scope_guard",
            "local_grounded",
            "local_curated",
            "model_grounded",
        ):
            graph.add_edge(node_name, "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    @staticmethod
    def _next_node(state: ChatbotState) -> str:
        return state["decision"]

    def _invoke_without_langgraph(self, state: ChatbotState) -> ChatbotState:
        state = self.nodes.prepare_context(state)
        state = self.nodes.route(state)

        node_by_decision: dict[str, Callable[[ChatbotState], ChatbotState]] = {
            "conversation_guard": self.nodes.conversation_guard,
            "general": self.nodes.general,
            "scope_guard": self.nodes.scope_guard,
            "local_grounded": self.nodes.local_grounded,
            "local_curated": self.nodes.local_curated,
            "model_grounded": self.nodes.model_grounded,
        }
        state = node_by_decision[state["decision"]](state)
        return self.nodes.finalize(state)
