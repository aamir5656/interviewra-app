from fastapi.testclient import TestClient

from app.main import create_app

app = create_app()


@app.get("/_t/{n}")
async def _t(n: int) -> dict[str, int]:
    return {"n": n}


client = TestClient(app)


def test_health_has_request_id() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["X-Request-ID"]


def test_validation_error_shape() -> None:
    r = client.get("/_t/abc")
    err = r.json()["error"]
    assert r.status_code == 422
    assert err["code"] == "validation_error"
    assert err["request_id"] == r.headers["X-Request-ID"]


def test_not_found_shape() -> None:
    assert client.get("/nope").json()["error"]["code"] == "not_found"


def test_body_too_large() -> None:
    r = client.post("/health", content=b"x" * (70 * 1024))
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
