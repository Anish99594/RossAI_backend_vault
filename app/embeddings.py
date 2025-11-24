import httpx
from app.config import settings

API_URL = "https://api.openai.com/v1/embeddings"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
}

def embed_batch(texts, batch_size=4):
    """
    Stream embedding in small batches (4 max).
    Prevents memory spikes.
    """
    all_embeddings = []

    with httpx.Client(timeout=None) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            payload = {
                "model": settings.EMBEDDING_MODEL,
                "input": batch
            }

            r = client.post(API_URL, json=payload, headers=HEADERS)
            r.raise_for_status()

            data = r.json()

            # append embeddings immediately
            for item in data["data"]:
                all_embeddings.append(item["embedding"])

            # free memory
            del batch
            del payload
            del data

    return all_embeddings
