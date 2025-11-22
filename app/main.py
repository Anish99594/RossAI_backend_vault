import os, hashlib, uuid
import json

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .auth import get_current_user, User
from .s3_client import upload_fileobj
from .pdf_utils import iter_pages_text, chunk_text
from .embeddings import embed_batch
from .pinecone_client import upsert_vectors
from .config import settings
from .db import SessionLocal
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
def check_access(session, user: User):
    if "admin" in user.roles:
        return  # admin can access everything

    q = text("""
        SELECT 1 FROM memberships
        WHERE user_id=:user_id
        AND company_id=:company_id
        AND team_id=:team_id
        AND project_id=:project_id
    """)

    row = session.execute(q, {
        "user_id": user.user_id,
        "company_id": user.company_id,
        "team_id": user.team_id,
        "project_id": user.project_id
    }).fetchone()

    if not row:
        raise HTTPException(403, "You do not have access to this project.")

# ----------------------------
# INSERT DOCUMENT INTO DB
# ----------------------------
def db_insert_document(session, company_id, team_id, project_id, user_id,
                       filename, s3_key, sha256, pages):
    q = text("""
    INSERT INTO documents (id, company_id, team_id, project_id, user_id,
                           filename, s3_key, sha256, pages)
    VALUES (gen_random_uuid(), :company_id, :team_id, :project_id,
            :user_id, :filename, :s3_key, :sha256, :pages)
    RETURNING id
    """)
    r = session.execute(q, {
        "company_id": company_id,
        "team_id": team_id,
        "project_id": project_id,
        "user_id": user_id,
        "filename": filename,
        "s3_key": s3_key,
        "sha256": sha256,
        "pages": pages
    })
    session.commit()
    return r.fetchone()[0]

# ----------------------------
# UPLOAD AUDIT LOG
# ----------------------------
def audit_insert(session, document_id, user, action, meta=None):
    q = text("""
    INSERT INTO uploads (document_id, user_id, team_id, project_id,
                         company_id, action, meta)
    VALUES (:document_id, :user_id, :team_id, :project_id, :company_id,
            :action, :meta)
    """)
    session.execute(q, {
        "document_id": document_id,
        "user_id": user.user_id,
        "team_id": user.team_id,
        "project_id": user.project_id,
        "company_id": user.company_id,
        "action": action,
        "meta": json.dumps(meta or {})  # JSON FIX
    })
    session.commit()

# ----------------------------
# UPLOAD & PROCESS PDF
# ----------------------------
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), user: User = Depends(get_current_user)):

    if file.content_type != "application/pdf":
        raise HTTPException(400, "Only PDF files are allowed")

    print(f"[UPLOAD] Received: {file.filename}", flush=True)
    session = SessionLocal()

    # 🔐 CHECK ACCESS
    check_access(session, user)

    # TEMP FILE
    tmp_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
    with open(tmp_path, "wb") as f:
        while True:
            block = await file.read(1024 * 1024)
            if not block:
                break
            f.write(block)

    print("[UPLOAD] Temp file saved", flush=True)

    # SHA256 CHECKSUM
    with open(tmp_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()
    print("[UPLOAD] SHA256 computed", flush=True)

    # UPLOAD ORIGINAL FILE TO MINIO
    s3_key = f"{user.company_id}/{user.team_id}/{user.project_id}/{user.user_id}/{uuid.uuid4()}_{file.filename}"
    with open(tmp_path, "rb") as f:
        upload_fileobj(f, settings.S3_BUCKET, s3_key)
    print("[UPLOAD] Uploaded to MinIO", flush=True)

    # ------------------------
    # PDF PROCESSING
    # ------------------------
    total_chunks = 0
    MAX_CHUNKS = 100
    page_count = 0

    for page_num, page_text in iter_pages_text(tmp_path):
        print(f"[PDF] Page {page_num} extracted:", flush=True)

        if not page_text or len(page_text.strip()) < 20:
            print(f"[WARN] Page {page_num} is empty — skipping.", flush=True)
            continue

        page_count += 1
        batch = []
        chunk_idx = 0

        for chunk in chunk_text(page_text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP):
            if not chunk.strip():
                continue

            if total_chunks >= MAX_CHUNKS:
                print("[STOP] Max chunk limit reached.", flush=True)
                break

            batch.append((chunk_idx, chunk))
            chunk_idx += 1

            if len(batch) == 4:
                try:
                    embeddings = embed_batch([c[1] for c in batch])
                except Exception:
                    print("[ERROR] Embedding failed.", flush=True)
                    batch.clear()
                    continue

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
                batch.clear()

        # leftover batch
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

    # ----------------------------
    # FIXED DB INSERT HERE
    # ----------------------------
    print("[DB] Writing record to DB...", flush=True)
    doc_id = db_insert_document(
        session,
        user.company_id,
        user.team_id,
        user.project_id,
        user.user_id,
        file.filename,
        s3_key,
        sha256,
        page_count  # last argument
    )

    audit_insert(session, doc_id, user, "ingest", {"chunks": total_chunks})
    session.close()

    os.remove(tmp_path)
    print("[UPLOAD] COMPLETED SUCCESSFULLY!", flush=True)

    return {"status": "ok", "doc_id": str(doc_id), "chunks": total_chunks}
