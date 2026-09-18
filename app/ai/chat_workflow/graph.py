from uuid import uuid4

from langgraph.graph import END, StateGraph

from app.ai.chat_workflow.memory import get_session
from app.ai.chat_workflow.nodes import (
    _get_rag_agent,
    availability_node,
    booking_node,
    choose_node,
    doctor_bio_node,
    fallback_node,
    route_intent,
    serialize_chunks,
)
from app.ai.chat_workflow.state import ClinicChatState
from app.database.schema import ChatRequest, ChatResponse, QueryRequest, QueryResponse

clinic_workflow = StateGraph(ClinicChatState)
clinic_workflow.add_node("route_intent", route_intent)
clinic_workflow.add_node("doctor_bio", doctor_bio_node)
clinic_workflow.add_node("availability", availability_node)
clinic_workflow.add_node("booking", booking_node)
clinic_workflow.add_node("fallback", fallback_node)
clinic_workflow.set_entry_point("route_intent")
clinic_workflow.add_conditional_edges(
    "route_intent",
    choose_node,
    {
        "doctor_bio": "doctor_bio",
        "availability": "availability",
        "booking": "booking",
        "fallback": "fallback",
    },
)
clinic_workflow.add_edge("doctor_bio", END)
clinic_workflow.add_edge("availability", END)
clinic_workflow.add_edge("booking", END)
clinic_workflow.add_edge("fallback", END)
clinic_chat_app = clinic_workflow.compile()


def run_clinic_chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid4())
    inputs: ClinicChatState = {
        "session_id": session_id,
        "message": request.message,
        "doctor_id": request.doctor_id,
        "appointment_date": request.appointment_date,
        "appointment_time": request.appointment_time,
        "patient": request.patient,
        "conversation": get_session(session_id),
    }
    result = clinic_chat_app.invoke(inputs)
    return ChatResponse(
        session_id=result["session_id"],
        intent=result.get("intent", "fallback"),
        response=result.get("response", ""),
        data=result.get("data", {}),
        chunks=result.get("chunks"),
    )


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
