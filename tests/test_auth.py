def test_unauthed_blocked(client):
    assert client.get("/api/clips").status_code == 401
    assert client.get("/api/clip/latest").status_code == 401


def test_bearer_token_auth(client, auth_headers):
    r = client.get("/api/clips", headers=auth_headers)
    assert r.status_code == 200
    assert r.json == []


def test_query_token_auth(client, token):
    r = client.get(f"/api/clips?token={token}")
    assert r.status_code == 200


def test_bad_token_rejected(client):
    r = client.get("/api/clips", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_login_logout(client):
    bad = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "hunter2hunter"},
    )
    assert ok.status_code == 200
    # session cookie now allows access
    assert client.get("/api/clips").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/clips").status_code == 401


def test_rotate_token_invalidates_old(client, auth_headers, token):
    r = client.post("/api/auth/rotate-token", headers=auth_headers)
    assert r.status_code == 200
    new_token = r.json["api_token"]
    assert new_token != token
    # old token no longer works
    assert client.get("/api/clips", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/api/clips", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_change_password(client, auth_headers):
    r = client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current": "wrong", "new": "newpasswordhere"},
    )
    assert r.status_code == 401
    r = client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current": "hunter2hunter", "new": "short"},
    )
    assert r.status_code == 400
    r = client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current": "hunter2hunter", "new": "newpasswordhere"},
    )
    assert r.status_code == 200
    bad = client.post(
        "/api/auth/login", json={"username": "alice", "password": "hunter2hunter"}
    )
    assert bad.status_code == 401
    good = client.post(
        "/api/auth/login", json={"username": "alice", "password": "newpasswordhere"}
    )
    assert good.status_code == 200
