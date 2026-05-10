"""
Kaigo Navigator — LangGraph Orchestrator.

Graph topology (Phase 1):
  intake → service_discovery → format_response → END

Human-in-the-loop gate fires before any write action (Phase 2+).
Each node is wrapped with Langfuse observability.
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from agents.state import CareState
from agents.service_discovery import service_discovery_node
from agents.paperwork import paperwork_node
from agents.scheduler import scheduling_node
from agents.monitoring import monitoring_node
from config.settings import get_settings
from observability.tracing import start_trace, trace_agent_step

settings = get_settings()


# ── Intake node ────────────────────────────────────────────────────────────

def intake_node(state: CareState) -> dict:
    """
    Validates incoming request and initialises a Langfuse trace.
    Rejects requests missing required fields.
    """
    trace = start_trace(
        name=f"care_request_{state.get('request_id', 'unknown')}",
        metadata={
            "ward": state.get("ward"),
            "patient_age": state.get("patient_age"),
            "care_level": state.get("care_level"),
        },
    )

    # Basic validation
    missing = [
        f for f in ("needs_description", "ward", "patient_age")
        if not state.get(f)
    ]
    if missing:
        return {
            "_trace": trace,
            "status": "error",
            "error": f"Missing required fields: {missing}",
            "current_agent": "intake",
        }

    trace_agent_step(
        trace, "intake",
        input_data=state.get("needs_description"),
        output_data="Request validated",
    )

    return {
        "_trace": None,   # never persist trace object to SQLite
        "status": "processing",
        "current_agent": "intake",
        "error": None,
        "messages": [],
        "awaiting_human_approval": False,
        "forms_required": [],
        "forms_prefilled": [],
        "scheduled_visits": [],
        "line_reminders": [],
        "schedule_meta": None,
        "care_plan_score": None,
        "monitoring_alerts": [],
        "monitoring_analysis": None,
    }


# ── Format response node ───────────────────────────────────────────────────

def format_response_node(state: CareState) -> dict:
    """
    Final node: summarises results into a human-readable message.
    Closes the Langfuse trace.
    """
    ranked = state.get("ranked_services", [])
    trace = state.get("_trace")

    if not ranked:
        summary = "No matching care services found for the given criteria."
        summary_jp = "条件に合うケアサービスが見つかりませんでした。"
    else:
        top = ranked[0]
        summary = (
            f"Top match: {top.get('name')} "
            f"(score: {top.get('match_score')}/100). "
            f"{top.get('reason_en', '')}"
        )
        summary_jp = (
            f"最適施設: {top.get('name')} "
            f"(スコア: {top.get('match_score')}/100). "
            f"{top.get('reason_jp', '')}"
        )

    score = state.get("care_plan_score")
    visits = state.get("scheduled_visits", [])
    score_str = f" | Plan score: {int(score)}/100" if score is not None else ""
    schedule_str = f" | {len(visits)} visits scheduled over 4 weeks" if visits else ""

    trace_agent_step(
        trace, "format_response",
        input_data=f"{len(ranked)} ranked services",
        output_data=summary + score_str,
    )

    if trace:
        try:
            trace.update(output={"summary_en": summary, "summary_jp": summary_jp})
        except Exception:
            pass

    return {
        "status": "complete",
        "current_agent": "format_response",
        "messages": state.get("messages", []) + [
            {"agent": "orchestrator", "content": summary + score_str + schedule_str},
            {"agent": "orchestrator_jp", "content": summary_jp},
        ],
    }


# ── Human approval gate (stub — active in Phase 2) ────────────────────────

def should_await_human(state: CareState) -> str:
    """
    Routing function.
    Returns "await_human" if a write action requires approval,
    otherwise routes to the next processing node.

    Phase 1: always routes straight through.
    Phase 2: will check state["awaiting_human_approval"].
    """
    if state.get("awaiting_human_approval"):
        return "await_human"
    if state.get("status") == "error":
        return "error"
    return "continue"


def human_gate_node(state: CareState) -> dict:
    """
    Pauses the graph and signals that human review is required.
    The API layer exposes a /approve endpoint to resume.
    """
    return {
        "status": "awaiting_human",
        "current_agent": "human_gate",
        "messages": state.get("messages", []) + [
            {
                "agent": "human_gate",
                "content": (
                    "Human approval required before submitting forms. "
                    "Please review and call /approve/{request_id}."
                ),
            }
        ],
    }


def error_node(state: CareState) -> dict:
    return {"status": "error", "current_agent": "error"}


# ── Build LangGraph ────────────────────────────────────────────────────────

def build_graph(checkpointer=None) -> StateGraph:
    graph = StateGraph(CareState)

    # Register nodes
    graph.add_node("intake", intake_node)
    graph.add_node("service_discovery", service_discovery_node)
    graph.add_node("paperwork", paperwork_node)
    graph.add_node("human_gate", human_gate_node)
    graph.add_node("scheduling", scheduling_node)
    graph.add_node("monitoring", monitoring_node)
    graph.add_node("format_response", format_response_node)
    graph.add_node("error", error_node)

    # Entry point
    graph.set_entry_point("intake")

    # intake → service_discovery (or error)
    graph.add_conditional_edges(
        "intake",
        should_await_human,
        {
            "continue": "service_discovery",
            "await_human": "human_gate",
            "error": "error",
        },
    )

    # service_discovery → paperwork (Phase 2+)
    graph.add_edge("service_discovery", "paperwork")

    # paperwork → human_gate (interrupt_before="human_gate" pauses graph here)
    graph.add_edge("paperwork", "human_gate")

    # After human approval resumes:
    # human_gate → scheduling → monitoring → format_response → END
    graph.add_edge("human_gate", "scheduling")
    graph.add_edge("scheduling", "monitoring")
    graph.add_edge("monitoring", "format_response")
    graph.add_edge("format_response", END)
    graph.add_edge("error", END)

    # interrupt_before human_gate: graph pauses BEFORE human_gate runs
    # First invoke returns after paperwork (awaiting_human status)
    # Second invoke (after approval) runs: human_gate → scheduling → monitoring → format_response
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_gate"] if checkpointer else [],
    )


# Compiled graph (no checkpointer — for simple runs)
kaigo_graph = build_graph()

# SQLite checkpointer path
DB_PATH = "data/kaigo_state.db"


def get_checkpointed_graph():
    """Return graph with SQLite checkpointer for human-in-the-loop flows."""
    import sqlite3
    import os
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return build_graph(checkpointer=checkpointer)


def run_care_request(
    needs_description: str,
    ward: str,
    patient_age: int,
    patient_name: str = "患者",
    care_level: int = 0,
) -> dict[str, Any]:
    """
    Runs a full care request through the graph with SQLite checkpointing.
    Pauses at human_gate for approval. Returns final state.
    """
    request_id = str(uuid.uuid4())[:8]
    initial_state: CareState = {
        "request_id": request_id,
        "patient_name": patient_name,
        "patient_age": patient_age,
        "ward": ward,
        "care_level": care_level,
        "needs_description": needs_description,
        "required_service_codes": [],
        "discovered_services": [],
        "ranked_services": [],
        "forms_required": [],
        "forms_prefilled": [],
        "awaiting_human_approval": False,
        "scheduled_visits": [],
        "line_reminders": [],
        "schedule_meta": None,
        "care_plan_score": None,
        "monitoring_alerts": [],
        "monitoring_analysis": None,
        "current_agent": "",
        "status": "processing",
        "error": None,
        "messages": [],
        "_trace": None,
    }

    graph = get_checkpointed_graph()
    config = {"configurable": {"thread_id": request_id}}

    # Strip non-serializable _trace before invoking with checkpointer
    initial_state["_trace"] = None
    result = graph.invoke(initial_state, config=config)

    # Graph paused before human_gate — mark as awaiting_human
    # (interrupt_before means paperwork ran but human_gate did not yet)
    if result and result.get("forms_prefilled"):
        graph.update_state(config, {"status": "awaiting_human"})
        result = dict(result)
        result["status"] = "awaiting_human"

    # Flush Langfuse
    try:
        from observability.tracing import get_client
        client = get_client()
        if client:
            client.flush()
    except Exception:
        pass

    return result


def approve_care_request(request_id: str) -> dict[str, Any]:
    """
    Resumes a paused graph after human approval.
    Clears awaiting_human_approval and continues to format_response.
    """
    graph = get_checkpointed_graph()
    config = {"configurable": {"thread_id": request_id}}

    # Resume graph from human_gate interrupt
    # (interrupt_before=human_gate means graph resumes by running human_gate → scheduling → monitoring → format_response)
    graph.update_state(config, {"awaiting_human_approval": False, "status": "processing"})
    result = graph.invoke(None, config=config)

    try:
        from observability.tracing import get_client
        client = get_client()
        if client:
            client.flush()
    except Exception:
        pass

    return result


def get_request_state(request_id: str) -> dict[str, Any]:
    """Fetch current state for a given request_id from SQLite."""
    graph = get_checkpointed_graph()
    config = {"configurable": {"thread_id": request_id}}
    snapshot = graph.get_state(config)
    return dict(snapshot.values) if snapshot else {}
