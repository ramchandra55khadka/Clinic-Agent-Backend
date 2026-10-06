
from langgraph.graph import END, StateGraph

from app.ai.chat_workflow.nodes import (
    _get_rag_agent,
    availability_node,
    booking_node,
    choose_node,
    doctor_bio_node,
    fallback_node,
    faq_node,
    medical_web_node,
    out_of_scope_node,
    route_intent,
    serialize_chunks,
)
from app.ai.chat_workflow.state import ClinicChatState
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.query import QueryRequest, QueryResponse

clinic_workflow = StateGraph(ClinicChatState)
clinic_workflow.add_node("route_intent", route_intent)
clinic_workflow.add_node("doctor_bio", doctor_bio_node)
clinic_workflow.add_node("availability", availability_node)
clinic_workflow.add_node("booking", booking_node)
clinic_workflow.add_node("fallback", fallback_node)
clinic_workflow.add_node("medical_web", medical_web_node)
clinic_workflow.add_node("out_of_scope", out_of_scope_node)
clinic_workflow.add_node("faq", faq_node)
clinic_workflow.set_entry_point("route_intent")
clinic_workflow.add_conditional_edges(
    "route_intent",
    choose_node,
    {
        "doctor_bio": "doctor_bio",
        "availability": "availability",
        "booking": "booking",
        "fallback": "fallback",
        "faq": "faq",
        "medical_web": "medical_web",
        "out_of_scope": "out_of_scope",
    },
)
clinic_workflow.add_edge("doctor_bio", END)
clinic_workflow.add_edge("availability", END)
clinic_workflow.add_edge("booking", END)
clinic_workflow.add_edge("fallback", END)
clinic_workflow.add_edge("medical_web", END)
clinic_workflow.add_edge("out_of_scope", END)
clinic_workflow.add_edge("faq", END)
clinic_chat_app = clinic_workflow.compile()


def run_clinic_chat(
    request: ChatRequest,
    session_id: str,
    conversation_state: dict,
    long_term_memories: list[str] | None = None,
    history: list[dict] | None = None,
    summary: str = "",
) -> tuple[ChatResponse, dict]:
    inputs: ClinicChatState = {
        "session_id": session_id,
        "message": request.message,
        "doctor_id": request.doctor_id,
        "appointment_date": request.appointment_date,
        "appointment_time": request.appointment_time,
        "patient": request.patient,
        "conversation": conversation_state,
        "long_term_memories": long_term_memories or [],
        "history": history or [],
        "summary": summary or "",
    }
    result = clinic_chat_app.invoke(inputs)
    chat_response = ChatResponse(
        session_id=result["session_id"],
        intent=result.get("intent", "fallback"),
        response=result.get("response", ""),
        data=result.get("data", {}),
        chunks=result.get("chunks"),
    )
    return chat_response, result.get("conversation", conversation_state)


def run_rag(request: QueryRequest) -> QueryResponse:
    agent = _get_rag_agent()
    result = agent.answer(
        query=request.query,
        top_k=request.top_k,
        system_prompt=request.system_prompt,
    )
    return QueryResponse(
        response=result.get("response", ""),
        chunks=serialize_chunks(result.get("chunks", [])),
    )
