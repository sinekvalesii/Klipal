import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402

c = A.app.test_client()


def test_pages_load():
    r = c.get("/")
    assert r.status_code == 200 and "Klipal" in r.get_data(as_text=True)
    assert c.get("/static/config.js").status_code == 200
    assert c.get("/manifest.webmanifest").status_code == 200
    assert c.get("/health").get_json()["ok"] is True


def test_url_helpers():
    assert A.normalize_url("bak https://vm.tiktok.com/ZMabc123/ !") == "https://vm.tiktok.com/ZMabc123/"
    assert A.detect_platform("https://fb.watch/abc/") == "facebook"
    assert A.detect_platform("https://x.com.evil.com/a") is None
    assert A.clean_title("Harika 🔥 video #fyp @kisi") == "Harika video"


def test_rejects_unsupported():
    assert c.post("/api/info", json={"url": "https://example.com/v"}).status_code == 400
    assert c.post("/api/download", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "quality": "99999"}).status_code == 400
    assert c.get("/api/job/yok").status_code == 404


def test_cors_for_pages():
    r = c.options("/api/info", headers={"Origin": "https://sinekvalesii.github.io",
                                        "Access-Control-Request-Method": "POST"})
    assert r.headers.get("Access-Control-Allow-Origin") == "https://sinekvalesii.github.io"
    r = c.options("/api/info", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers
