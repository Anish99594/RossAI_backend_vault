from pinecone import Pinecone
from .config import settings
import time
import traceback

pc = Pinecone(api_key=settings.PINECONE_API_KEY)
index = pc.Index(settings.PINECONE_INDEX)


def upsert_vectors(namespace: str, items: list):
    """
    items = [(id, vector, metadata), ...]
    """
    vectors = []
    for vid, vec, meta in items:
        vectors.append({
            "id": vid,
            "values": vec,
            "metadata": meta
        })

    print(f"[PINECONE] Preparing to upsert {len(vectors)} vectors...", flush=True)
    start = time.time()

    try:
        result = index.upsert(
            vectors=vectors,
            namespace=namespace,
            timeout=10  # <--- **VERY IMPORTANT**
        )

        elapsed = time.time() - start
        print(f"[PINECONE] Upsert OK ({elapsed:.2f}s)", flush=True)
        return result

    except Exception as e:
        print("[PINECONE] ERROR during upsert:", flush=True)
        traceback.print_exc()
        raise


def query_vector(namespace: str, vector: list, top_k: int = 5):
    print("[PINECONE] Querying vector...", flush=True)
    try:
        result = index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True,
            namespace=namespace,
            timeout=10
        )
        print("[PINECONE] Query OK", flush=True)
        return result
    except Exception as e:
        print("[PINECONE] ERROR during query:", flush=True)
        traceback.print_exc()
        return {"matches": []}
