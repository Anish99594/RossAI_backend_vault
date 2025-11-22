import io
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.auth import User, get_current_user
import app.main as main


class DummySession:
    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return ["doc-id"]

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture(autouse=True)
def override_dependencies():
    user = User(
        user_id="user-1",
        team_id="team-a",
        project_id="project-alpha",
        company_id="company-x",
        roles=["member"],
    )

    def _get_user():
        return user

    app.dependency_overrides[get_current_user] = _get_user
    original_session = main.SessionLocal
    main.SessionLocal = lambda: DummySession()
    yield user
    app.dependency_overrides.clear()
    main.SessionLocal = original_session


client = TestClient(app)


def test_query_enforces_company_team_project(monkeypatch, override_dependencies):
    captured = {}

    def fake_embed_texts(texts):
        return [[0.0] * 10 for _ in texts]

    def fake_query_vector(namespace, vector, top_k, filter_):
        captured["namespace"] = namespace
        captured["filter"] = filter_
        return {"matches": []}

    def fake_audit_insert(*args, **kwargs):
        pass

    monkeypatch.setattr(main, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(main, "query_vector", fake_query_vector)
    monkeypatch.setattr(main, "audit_insert", fake_audit_insert)

    res = client.post("/query", json={"query": "test question"})
    assert res.status_code == 200
    assert captured["namespace"] == override_dependencies.company_id
    assert captured["filter"] == {
        "company_id": {"$eq": override_dependencies.company_id},
        "team_id": {"$eq": override_dependencies.team_id},
        "project_id": {"$eq": override_dependencies.project_id},
    }


def test_upload_attaches_project_metadata(monkeypatch, override_dependencies):
    captured = {}

    def fake_upload_fileobj(*args, **kwargs):
        pass

    def fake_extract_pages_text(*args, **kwargs):
        return ["page text"]

    def fake_chunk_text(*args, **kwargs):
        return ["chunk text"]

    def fake_embed_texts(texts):
        return [[0.0] * 10 for _ in texts]

    def fake_upsert_vectors(namespace, items):
        captured["namespace"] = namespace
        captured["items"] = items

    def fake_db_insert_document(*args, **kwargs):
        return "doc-123"

    def fake_audit_insert(*args, **kwargs):
        pass

    monkeypatch.setattr(main, "upload_fileobj", fake_upload_fileobj)
    monkeypatch.setattr(main, "extract_pages_text", fake_extract_pages_text)
    monkeypatch.setattr(main, "chunk_text", fake_chunk_text)
    monkeypatch.setattr(main, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(main, "upsert_vectors", fake_upsert_vectors)
    monkeypatch.setattr(main, "db_insert_document", fake_db_insert_document)
    monkeypatch.setattr(main, "audit_insert", fake_audit_insert)

    res = client.post(
        "/upload",
        files={"file": ("doc.pdf", io.BytesIO(b"fake pdf"), "application/pdf")},
    )

    assert res.status_code == 200
    assert captured["namespace"] == override_dependencies.company_id
    assert len(captured["items"]) == 1
    _, _, metadata = captured["items"][0]
    assert metadata["company_id"] == override_dependencies.company_id
    assert metadata["team_id"] == override_dependencies.team_id
    assert metadata["project_id"] == override_dependencies.project_id



