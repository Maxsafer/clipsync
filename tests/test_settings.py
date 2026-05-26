def test_get_defaults(client, auth_headers):
    r = client.get("/api/settings", headers=auth_headers)
    assert r.status_code == 200
    assert r.json == {"history_size": 50, "item_ttl_hours": 24, "max_item_size_mb": 100}


def test_update_settings(client, auth_headers):
    r = client.post(
        "/api/settings",
        headers=auth_headers,
        json={"history_size": 10, "item_ttl_hours": 0, "max_item_size_mb": 5},
    )
    assert r.status_code == 200
    assert r.json["history_size"] == 10
    assert r.json["item_ttl_hours"] == 0
    assert r.json["max_item_size_mb"] == 5


def test_rejects_unknown_keys(client, auth_headers):
    r = client.post("/api/settings", headers=auth_headers, json={"shenanigans": 1})
    assert r.status_code == 400


def test_rejects_negative(client, auth_headers):
    r = client.post("/api/settings", headers=auth_headers, json={"history_size": -1})
    assert r.status_code == 400


def test_settings_require_auth(client):
    assert client.get("/api/settings").status_code == 401
    assert client.post("/api/settings", json={"history_size": 10}).status_code == 401
