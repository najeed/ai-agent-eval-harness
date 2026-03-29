import pytest
from eval_runner.console.auth import generate_handoff_token, SECRET_KEY
from eval_runner.console.app import create_app
import jwt


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_handoff_token_generation():
    token = generate_handoff_token()
    assert token is not None
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    assert payload["scope"] == "console-handoff"
    assert "exp" in payload


def test_handoff_endpoint(client):
    response = client.get("/api/auth/handoff")
    assert response.status_code == 200
    data = response.get_json()
    assert "token" in data


def test_nav_metadata(client):
    response = client.get("/api/nav")
    assert response.status_code == 200
    data = response.get_json()
    nav = data["nav"]
    # Check if type is present in all core items
    for item in nav:
        assert "type" in item
        if item["id"] == "community":
            assert item["type"] == "external"


def test_secure_route_protection(client):
    # This requires a decorated route. We can mock one or use a real one if available.
    # For now, just verifying the decorator logic exists in auth.py
    from eval_runner.console.auth import handoff_required
    from flask import Flask, jsonify

    app = Flask(__name__)

    @app.route("/secure")
    @handoff_required
    def protected():
        return jsonify({"status": "ok"})

    with app.test_client() as test_client:
        # No token
        res = test_client.get("/secure")
        assert res.status_code == 401

        # Valid token
        token = generate_handoff_token()
        res = test_client.get(f"/secure?token={token}")
        assert res.status_code == 200
