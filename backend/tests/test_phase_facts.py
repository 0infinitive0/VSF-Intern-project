"""`phase_facts` decides what a progress frame may reveal.

Every update dict it sees is real: the shapes come from a graph run recorded
2026-08-19, not from reading `return` statements. Two of them are the reason
this module is a whitelist — `load_context` returns the entire state, and
`supervisor` returns prose the LLM wrote.
"""

from __future__ import annotations

import pytest

from src.agents.graph.phase_facts import phase_facts

# --- Observed updates, verbatim ---------------------------------------------

_EXTRACT_PATCH_UPDATE = {
    "patch": [
        {"path": "people", "operation": "set", "value": 3},
        {"path": "budget.target", "operation": "set", "value": 8_000_000},
    ],
    "intent": "update_trip",
    "extraction_failed": False,
    "patch_reason": "",
    "pending_clarify_day": None,
}

_SUPERVISOR_UPDATE = {
    "next_worker": "hotel_node",
    "task_description": "auto-routed to hotel_node via impact_map",
    "routing_source": "impact_map",
    "routing_reasoning": "",
    "supervisor_iterations": 1,
}

_LOAD_CONTEXT_UPDATE = {
    "travel_state": {"destination": {"presence": "set", "value": "Đà Nẵng"}},
    "response": {"reply": "một câu trả lời đầy đủ", "session_id": "s-1"},
    "task_results": [{"worker": "hotel_node", "status": "error", "reply": "..."}],
    "intent": "",
    "patch": [],
    "jailbreak_blocked": False,
}


class TestWhatIsPublished:
    def test_extract_patch_publishes_intent_and_field_paths(self):
        assert phase_facts("extract_patch", _EXTRACT_PATCH_UPDATE) == {
            "intent": "update_trip",
            "fields": ["people", "budget.target"],
        }

    def test_field_values_never_leave_with_their_paths(self):
        """A path names a schema field; a value is what the user typed."""
        facts = phase_facts("extract_patch", _EXTRACT_PATCH_UPDATE)

        assert "8000000" not in str(facts)
        assert "Đà Nẵng" not in str(facts)

    def test_supervisor_publishes_only_the_worker(self):
        assert phase_facts("supervisor", _SUPERVISOR_UPDATE) == {"worker": "hotel_node"}

    def test_supervisor_prose_never_reaches_the_wire(self):
        """`task_description` and `routing_reasoning` are written by the LLM.
        The phase contract says the backend sends keys and numbers, never display
        text — and these two sit in the same dict as the field that is allowed."""
        facts = phase_facts("supervisor", _SUPERVISOR_UPDATE)

        assert "auto-routed" not in str(facts)
        assert "impact_map" not in str(facts)


class TestDefaultDeny:
    def test_load_context_publishes_nothing_despite_holding_everything(self):
        """It returns the whole graph state, including the finished reply. It has
        a phase key (`compacting_history`), so only the whitelist keeps it quiet."""
        assert phase_facts("load_context", _LOAD_CONTEXT_UPDATE) == {}

    @pytest.mark.parametrize(
        "node", ["respond", "hotel_node", "qa_node", "validate_patch", "ask_slot", "apply_patch"]
    )
    def test_an_unlisted_node_publishes_nothing(self, node):
        assert phase_facts(node, {"anything": "at all", "reply": "leak me"}) == {}

    def test_an_unknown_field_inside_a_listed_node_is_still_dropped(self):
        facts = phase_facts(
            "extract_patch", {**_EXTRACT_PATCH_UPDATE, "secret_token": "leak-me"}
        )

        assert "leak-me" not in str(facts)
        assert set(facts) == {"intent", "fields"}


class TestAbsentFactsAreAbsent:
    def test_no_intent_and_no_patch_yields_no_keys(self):
        """Not `null`, not `0` — the key simply is not sent."""
        assert phase_facts("extract_patch", {"intent": "", "patch": []}) == {}

    def test_a_missing_key_is_not_an_error(self):
        assert phase_facts("extract_patch", {}) == {}

    def test_an_empty_worker_is_not_a_fact(self):
        assert phase_facts("supervisor", {"next_worker": ""}) == {}


class TestItCannotCostTheUserTheirTurn:
    def test_a_node_returning_none_is_handled(self):
        """`scope_guard` really does return `None` — measured, not hypothetical."""
        assert phase_facts("scope_guard", None) == {}
        assert phase_facts("extract_patch", None) == {}

    @pytest.mark.parametrize("update", ["a string", 42, [], ("tuple",)])
    def test_a_non_dict_update_is_handled(self, update):
        assert phase_facts("extract_patch", update) == {}

    def test_a_malformed_patch_does_not_raise(self):
        assert phase_facts("extract_patch", {"patch": "not a list", "intent": "x"}) == {"intent": "x"}
        assert phase_facts("extract_patch", {"patch": [None, 5, {"no_path": 1}]}) == {}

    def test_an_extractor_that_explodes_is_contained(self, monkeypatch):
        import src.agents.graph.phase_facts as module

        def _boom(_update):
            raise RuntimeError("bug in an extractor")

        monkeypatch.setitem(module._EXTRACTORS, "extract_patch", _boom)

        assert phase_facts("extract_patch", _EXTRACT_PATCH_UPDATE) == {}


def test_the_field_list_is_bounded():
    """A 200-change patch must not turn one progress frame into a payload."""
    patch = [{"path": f"days.{i}.activities", "operation": "set", "value": i} for i in range(200)]

    fields = phase_facts("extract_patch", {"patch": patch, "intent": "update_trip"})["fields"]

    assert len(fields) == 12
