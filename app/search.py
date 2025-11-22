# search.py
from fastapi import APIRouter, Depends
from .auth import get_current_user, User
from .embeddings import embed_batch
from .pinecone_client import query_vector

router = APIRouter()

@router.get("/search")
def search_docs(query: str, user: User = Depends(get_current_user)):
    # 1) Embed user query
    query_embedding = embed_batch([query])[0]

    # 2) Query Pinecone
    result = query_vector(
        namespace=user.company_id,
        vector=query_embedding,
        top_k=5
    )

    # ❗ FIX – now use hasattr() to avoid KeyError
    matches = getattr(result, "matches", None)

    if not matches:
        return {"answer": "No relevant documents found."}

    # 3) Safely extract metadata
    context = []
    for match in matches:
        meta = getattr(match, "metadata", {})  # safe access

        context.append({
            "filename": meta.get("doc_name", "N/A"),
            "page": meta.get("page", "N/A"),
            "content": meta.get("text", "⚠️ No text found"),
            "score": getattr(match, "score", None),
        })

    return {
        "answer": f"Found {len(context)} relevant chunks:",
        "results": context
    }
