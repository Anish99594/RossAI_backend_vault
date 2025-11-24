# chat.py
from fastapi import APIRouter, Depends
from openai import OpenAI  # <--- 1. New Import
from .auth import get_current_user, User
from .embeddings import embed_batch
from .pinecone_client import query_vector
from app.config import settings

router = APIRouter()

# 2. Initialize Client
client = OpenAI(api_key=settings.OPENAI_API_KEY)

@router.get("/chat")
async def chat(query: str, user: User = Depends(get_current_user)):
    # 1) Embed question
    query_emb = embed_batch([query])[0]

    # 2) Search best docs
    result = query_vector(
        namespace=user.company_id,
        vector=query_emb,
        top_k=5
    )

    # 🚀 Pinecone v4 returns object, not dict!
    matches = getattr(result, "matches", [])

    if not matches:
        return {"answer": "No relevant information found in your documents."}

    # 3) Build context string
    context = "\n---\n".join([
        f"Page {m.metadata.get('page')}: {m.metadata.get('text', '')}"
        for m in matches
    ])

    # 4) Ask LLM to answer using context
    messages = [
        {"role": "system", "content": "You are a helpful AI that answers based ONLY on the provided document."},
        {"role": "user", "content": f"Use ONLY this context:\n\n{context}\n\nQuestion: {query}"}
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )
    answer = response.choices[0].message.content
    return {"answer": answer}
