"""
Chat API endpoints: send queries, manage conversations.
"""
import json
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models import Conversation, Message
from app.schemas import (
    ChatRequest, ChatResponse, ConversationSummary,
    ConversationDetail, MessageResponse,
)
from app.services.retrieval import hybrid_search, parse_query_filters
from app.services.llm import generate_response, generate_response_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Send a query and get a RAG-powered response.
    Supports both streaming (SSE) and non-streaming modes.
    """
    # Get or create conversation
    conversation = None
    if request.conversation_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == request.conversation_id)
        )
        conversation = result.scalar_one_or_none()

    if not conversation:
        conversation = Conversation(title=request.query[:100])
        db.add(conversation)
        await db.flush()

    # Get conversation history
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in history_result.scalars()
    ]

    # Retrieve relevant problems
    parsed_filters = parse_query_filters(request.query)
    retrieved = await hybrid_search(
        query=request.query,
        db=db,
        filters=request.filters,
        top_k=parsed_filters.get("limit", 10),
    )

    # Save user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=request.query,
        metadata_={"filters": parsed_filters},
    )
    db.add(user_msg)
    await db.flush()

    if request.stream:
        # SSE streaming response
        async def event_generator():
            full_response = ""
            try:
                # Send retrieved problems metadata first
                yield {
                    "event": "metadata",
                    "data": json.dumps({
                        "conversation_id": str(conversation.id),
                        "parsed_filters": parsed_filters,
                        "retrieved_count": len(retrieved),
                        "retrieved_problems": [
                            {
                                "contest_id": r.get("contest_id"),
                                "problem_index": r.get("problem_index"),
                                "name": r.get("name"),
                                "rating": r.get("rating"),
                                "tags": r.get("tags"),
                                "url": r.get("url"),
                                "score": r.get("score"),
                            }
                            for r in retrieved
                        ],
                    }),
                }

                async for chunk in generate_response_stream(
                    query=request.query,
                    retrieved_results=retrieved,
                    mode=request.mode,
                    conversation_history=history,
                ):
                    full_response += chunk
                    yield {"event": "token", "data": chunk}

                # Save assistant message
                async with db.begin():
                    assistant_msg = Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content=full_response,
                        metadata_={
                            "retrieved_problems": [
                                {"contest_id": r.get("contest_id"), "index": r.get("problem_index")}
                                for r in retrieved
                            ],
                        },
                    )
                    db.add(assistant_msg)

                yield {"event": "done", "data": ""}

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                yield {"event": "error", "data": str(e)}

        return EventSourceResponse(event_generator())

    else:
        # Non-streaming response
        response_text = await generate_response(
            query=request.query,
            retrieved_results=retrieved,
            mode=request.mode,
            conversation_history=history,
        )

        # Save assistant message
        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=response_text,
            metadata_={
                "retrieved_problems": [
                    {"contest_id": r.get("contest_id"), "index": r.get("problem_index")}
                    for r in retrieved
                ],
            },
        )
        db.add(assistant_msg)

        return ChatResponse(
            response=response_text,
            conversation_id=str(conversation.id),
            retrieved_problems=[
                {
                    "contest_id": r.get("contest_id"),
                    "problem_index": r.get("problem_index"),
                    "name": r.get("name"),
                    "rating": r.get("rating"),
                    "tags": r.get("tags"),
                    "url": r.get("url"),
                }
                for r in retrieved
            ],
            parsed_filters=parsed_filters,
        )


@router.get("/conversations")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    """List all conversations, most recent first."""
    result = await db.execute(
        select(
            Conversation,
            func.count(Message.id).label("msg_count"),
        )
        .outerjoin(Message)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
    )

    conversations = []
    for conv, msg_count in result:
        conversations.append(ConversationSummary(
            id=str(conv.id),
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=msg_count,
        ))

    return conversations


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """Get full conversation with messages."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    )

    messages = [
        MessageResponse(
            id=str(msg.id),
            role=msg.role,
            content=msg.content,
            metadata=msg.metadata_,
            created_at=msg.created_at,
        )
        for msg in msg_result.scalars()
    ]

    return ConversationDetail(
        id=str(conv.id),
        title=conv.title,
        messages=messages,
        created_at=conv.created_at,
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a conversation and its messages."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conv)
    return {"status": "deleted"}
