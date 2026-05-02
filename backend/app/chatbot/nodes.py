from __future__ import annotations

from typing import Any

from app.chatbot.state import ChatDecision, ChatbotState


class BakeryChatbotNodes:
    def __init__(self, chatbot: Any) -> None:
        self.chatbot = chatbot

    def prepare_context(self, state: ChatbotState) -> ChatbotState:
        query = state["query"]
        history = state.get("history") or []
        context = self.chatbot._build_context(query, history)
        source_lookup = {source["id"]: source for source in context["sources"]}
        return {
            **state,
            "history": history,
            "context": context,
            "source_lookup": source_lookup,
        }

    def route(self, state: ChatbotState) -> ChatbotState:
        context = state["context"]
        history = state.get("history") or []

        if self.chatbot._is_greeting(context["queryNorm"]) and self.chatbot._assistant_already_greeted(history):
            decision: ChatDecision = "conversation_guard"
        elif not context["inScope"]:
            decision = "general" if self.chatbot.scope_mode == "hybrid_general" and self.chatbot.api_key else "scope_guard"
        elif self.chatbot._is_policy_query(context["queryNorm"]) and context["policyHits"]:
            decision = "local_grounded"
        elif not self.chatbot.api_key:
            decision = "local_grounded"
        elif self.chatbot._is_popular_products_query(context["queryNorm"]) and context["productHits"]:
            decision = "local_curated"
        else:
            decision = "model_grounded"

        return {**state, "decision": decision}

    def conversation_guard(self, state: ChatbotState) -> ChatbotState:
        raw = self.chatbot._build_local_answer(state["query"], state["context"], history=state.get("history"))
        return {**state, "raw_response": raw, "used_model": "conversation-guard"}

    def general(self, state: ChatbotState) -> ChatbotState:
        try:
            raw = self.chatbot._call_gemini_with_prompt(
                self.chatbot._build_general_prompt(state["query"], state.get("history") or [])
            )
            raw["scope"] = "general"
            raw["source_ids"] = []
            return {**state, "raw_response": raw, "used_model": f"{self.chatbot.model} (general)"}
        except Exception:
            return self.scope_guard(state)

    def scope_guard(self, state: ChatbotState) -> ChatbotState:
        raw = self.chatbot._build_local_answer(state["query"], state["context"], history=state.get("history"))
        return {**state, "raw_response": raw, "used_model": "scope-guard"}

    def local_grounded(self, state: ChatbotState) -> ChatbotState:
        raw = self.chatbot._build_local_answer(
            state["query"],
            state["context"],
            api_note=self.chatbot._friendly_fallback_note(None),
            history=state.get("history"),
        )
        return {**state, "raw_response": raw, "used_model": "local-grounded"}

    def local_curated(self, state: ChatbotState) -> ChatbotState:
        raw = self.chatbot._build_local_answer(state["query"], state["context"], history=state.get("history"))
        return {**state, "raw_response": raw, "used_model": "local-curated"}

    def model_grounded(self, state: ChatbotState) -> ChatbotState:
        try:
            raw = self.chatbot._call_gemini_with_prompt(
                self.chatbot._build_grounded_prompt(state["query"], state.get("history") or [], state["context"])
            )
            return {**state, "raw_response": raw, "used_model": self.chatbot.model}
        except Exception as exc:
            raw = self.chatbot._build_local_answer(
                state["query"],
                state["context"],
                api_note=self.chatbot._friendly_fallback_note(exc),
                history=state.get("history"),
            )
            return {**state, "raw_response": raw, "used_model": "local-grounded"}

    def finalize(self, state: ChatbotState) -> ChatbotState:
        response = self.chatbot._finalize_response(
            state["raw_response"],
            state["source_lookup"],
            state["used_model"],
            state["context"],
            state["query"],
            state.get("history"),
        )
        return {**state, "response": response}
