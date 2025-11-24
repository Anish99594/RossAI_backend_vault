import os, hashlib, uuid
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .auth import get_current_user, User
from .pdf_utils import iter_pages_text, chunk_text
from .embeddings import embed_batch
from .pinecone_client import upsert_vectors
from app.config import settings
from .db import get_db
from .login import router as login_router
from .access import router as access_router
from .search import router as search_router
from .chat import router as chat_router

app = FastAPI(title="SecureVault")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(login_router)
app.include_router(access_router)
app.include_router(search_router)
app.include_router(chat_router)

# ----------------------------
# ACCESS CHECK FUNCTION
# ----------------------------
def check_access(db, user: User):
    if "admin" in user.roles or "owner" in user.roles:
        return  # admin/owner can access everything

    membership = db.memberships.find_one({
        "user_id": user.user_id,
        "company_id": user.company_id,
        "team_id": user.team_id,
        "project_id": user.project_id
    })

    if not membership:
        raise HTTPException(403, "You do not have access to this project")

# ----------------------------
# INSERT DOCUMENT INTO DB
# ----------------------------
def db_insert_document(db, company_id, team_id, project_id, user_id,
                       filename, sha256, pages):
    doc = {
        "_id": str(uuid.uuid4()),
        "company_id": company_id,
        "team_id": team_id,
        "project_id": project_id,
        "user_id": user_id,
        "filename": filename,          # ❌ MinIO removed
        "sha256": sha256,
        "pages": pages,
        "created_at": datetime.utcnow()
    }
    result = db.documents.insert_one(doc)
    return result.inserted_id

# ----------------------------
# UPLOAD AUDIT LOG
# ----------------------------
def audit_insert(db, document_id, user, action, meta=None):
    audit = {
        "document_id": str(document_id),
        "user_id": user.user_id,
        "team_id": user.team_id,
        "project_id": user.project_id,
        "company_id": user.company_id,
        "action": action,
        "meta": meta or {},
        "created_at": datetime.utcnow()
    }
    db.uploads.insert_one(audit)

# ----------------------------
# UPLOAD & PROCESS PDF
# ----------------------------
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    if file.content_type != "application/pdf":
        raise HTTPException(400, "Only PDF files are allowed")

    print(f"[UPLOAD] Received: {file.filename}", flush=True)
    db = get_db()

    # 🔐 CHECK ACCESS — only allowed team/company/project
    check_access(db, user)

    # Read file entirely in-memory (NO STORAGE)
    file_bytes = await file.read()

    # SHA256 checksum
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    print("[UPLOAD] SHA256 computed", flush=True)

    # --- TEMP FILE for PDF parsing ---
    tmp_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
    with open(tmp_path, "wb") as tmp_file:
        tmp_file.write(file_bytes)

    # ------------------------
    # PDF PROCESSING
    # ------------------------
    total_chunks = 0
    MAX_CHUNKS = 100
    page_count = 0

    for page_num, page_text in iter_pages_text(tmp_path):
        if not page_text or len(page_text.strip()) < 20:
            continue

        page_count += 1
        batch = []
        chunk_idx = 0

        for chunk in chunk_text(page_text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP):
            if not chunk.strip():
                continue

            if total_chunks >= MAX_CHUNKS:
                break

            batch.append((chunk_idx, chunk))
            chunk_idx += 1

            if len(batch) == 4:
                embeddings = embed_batch([c[1] for c in batch])
                upserts = []
                for (idx, chunk_text_), emb in zip(batch, embeddings):
                    vid = hashlib.sha256(
                        (file.filename + str(page_num) + str(idx) + user.user_id).encode()
                    ).hexdigest()

                    meta = {
                        "company_id": user.company_id,
                        "team_id": user.team_id,
                        "project_id": user.project_id,
                        "user_id": user.user_id,
                        "doc_name": file.filename,
                        "page": page_num,
                        "chunk_index": idx,
                        "text": chunk_text_
                    }
                    upserts.append((vid, emb, meta))

                upsert_vectors(namespace=user.company_id, items=upserts)
                total_chunks += len(upserts)
                batch.clear()

        if batch:
            embeddings = embed_batch([c[1] for c in batch])
            upserts = []
            for (idx, chunk_text_), emb in zip(batch, embeddings):
                vid = hashlib.sha256((file.filename + str(page_num) + str(idx) + user.user_id).encode()).hexdigest()
                meta = {
                    "company_id": user.company_id,
                    "team_id": user.team_id,
                    "project_id": user.project_id,
                    "user_id": user.user_id,
                    "doc_name": file.filename,
                    "page": page_num,
                    "chunk_index": idx,
                    "text": chunk_text_
                }
                upserts.append((vid, emb, meta))

            upsert_vectors(namespace=user.company_id, items=upserts)
            total_chunks += len(upserts)

    # --- Insert MongoDB record ---
    doc_id = db_insert_document(
        db,
        user.company_id,
        user.team_id,
        user.project_id,
        user.user_id,
        file.filename,
        sha256,
        page_count
    )

    audit_insert(db, doc_id, user, "ingest", {"chunks": total_chunks})

    os.remove(tmp_path)
    return {"status": "ok", "doc_id": str(doc_id), "chunks": total_chunks}
