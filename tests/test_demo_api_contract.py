from types import SimpleNamespace

from fastapi.testclient import TestClient

from ai_presales_copilot.api_v2 import _public_state, create_fastapi_app
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.persistence import CheckpointStore


class HealthyModel:
    model = "test-model"

    def __init__(self, status: int = 200):
        self.status = status

    def health(self):
        return {"status": self.status}


def test_public_state_exposes_only_clarify_projection():
    public = _public_state({"clarify": {"missing_fields": ["deployment"], "questions": ["确认部署"]}, "policy": {"secret": "hidden"}})
    assert public["clarify"] == {"missing_fields": ["deployment"], "questions": ["确认部署"]}
    assert "policy" not in public


def test_readyz_reports_dependencies_and_healthz_stays_process_only():
    with CheckpointStore(":memory:") as store:
        app = create_fastapi_app(
            SimpleNamespace(model=HealthyModel()),
            store,
            KnowledgeBase("data/knowledge"),
        )
        client = TestClient(app)
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        assert client.get("/healthz").status_code == 200

        broken_app = create_fastapi_app(
            SimpleNamespace(model=HealthyModel(status=503)),
            store,
            KnowledgeBase("data/knowledge"),
        )
        broken_client = TestClient(broken_app)
        assert broken_client.get("/readyz").status_code == 503
        assert broken_client.get("/readyz").json()["checks"]["model"] is False
        assert broken_client.get("/healthz").status_code == 200
