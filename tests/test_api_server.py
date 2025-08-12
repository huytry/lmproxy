import os
import json
import types
import asyncio
from typing import List

import pytest

# Prefer httpx TestClient for FastAPI if available, else fallback to fastapi TestClient
try:
    import importlib as _importlib
    _importlib.import_module("httpx")
    _importlib.import_module("anyio")
    HAS_HTTPX = True
except Exception:
    HAS_HTTPX = False
from fastapi.testclient import TestClient


# NOTE ON TESTING LIBRARY AND FRAMEWORK:
# These tests are written for pytest with FastAPI's TestClient.
# If the project uses httpx.AsyncClient + anyio, the async variants included here will integrate with pytest as well.


# --- Utilities for patching/mocking and setup ---


class DummyWS:
    def __init__(self):
        self.sent_texts: List[str] = []
        self.client_state = types.SimpleNamespace(name='CONNECTED')
    async def send_text(self, s: str):
        self.sent_texts.append(s)


@pytest.fixture(autouse=True)
def clean_env_and_files(tmp_path, monkeypatch):
    # Prevent automatic updater from hitting the network by default
    monkeypatch.setenv("LM_BRIDGE_DISABLE_AUTO_UPDATE", "1")

    # Provide minimal config.jsonc, models.json, and model_endpoint_map.json in CWD
    # so functions that attempt to read them don't error.
    cfg = tmp_path / "config.jsonc"
    models = tmp_path / "models.json"
    model_map = tmp_path / "model_endpoint_map.json"
    avail_models = tmp_path / "available_models.json"

    cfg.write_text(
        """
        {
          // comment ok
          "version": "0.0.1",
          "tavern_mode_enabled": false,
          "bypass_enabled": false,
          "id_updater_last_mode": "direct_chat",
          "id_updater_battle_target": "A",
          "enable_auto_update": false,
          "enable_idle_restart": false,
          "stream_response_timeout_seconds": 1,
          "use_default_ids_if_mapping_not_found": true,
          "session_id": "SESSION_OK",
          "message_id": "MESSAGE_OK",
          "api_key": "secret-key"
        }
        """,
        encoding="utf-8"
    )
    models.write_text(json.dumps({
        "test-model": "model-id-123",
        "another-model": "model-id-456"
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    model_map.write_text(json.dumps({
        # Map a model to a single endpoint mapping including mode overrides
        "mapped-model": {
            "session_id": "SESSION_MAPPED",
            "message_id": "MESSAGE_MAPPED",
            "mode": "battle",
            "battle_target": "B"
        },
        # Map a model to a list of candidates (we won't rely on randomness here)
        "mapped-list-model": [
            {"session_id": "SESSION_A", "message_id": "MESSAGE_A"},
            {"session_id": "SESSION_B", "message_id": "MESSAGE_B"}
        ]
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    avail_models.write_text("[]", encoding="utf-8")

    # Chdir to temp dir so the app reads from here
    cwd = os.getcwd()
    monkeypatch.chdir(tmp_path)

    yield

    # restore cwd if needed
    os.chdir(cwd)

@pytest.fixture
def import_api(monkeypatch):
    """
    Import the api_server module while patching network-heavy functions.
    """
    # Defer import until fixture to ensure temp files and env are ready
    import importlib

    # Patch modules.image_generation with a minimal stub that matches required interface
    dummy_image_mod = types.SimpleNamespace(
        initialize_image_module=lambda **kwargs: None
    )
    async def stub_handle_image_generation_request(request, browser_ws):
        return {"ok": True, "via": "stub"}, 200
    dummy_image_mod.handle_image_generation_request = stub_handle_image_generation_request
    # To satisfy "from modules import image_generation"
    mod_modules = types.ModuleType("modules")
    mod_modules.image_generation = dummy_image_mod
    import sys
    monkeypatch.setitem(sys.modules, "modules", mod_modules)
    monkeypatch.setitem(sys.modules, "modules.image_generation", dummy_image_mod)

    # Guard requests to GitHub in check_for_updates by patching requests.get to raise if called

    # Ensure requests exists; then patch get to raise if used in check_for_updates
    try:
        import requests as _requests
        def _blocked_get(*args, **kwargs):
            raise RuntimeError("Network blocked in tests")
        monkeypatch.setattr(_requests, "get", _blocked_get, raising=True)
    except Exception:
        pass

    # Now import the module
    api_server = importlib.import_module("api_server")
    return api_server

@pytest.fixture
def client(import_api, monkeypatch):
    """
    Provide a TestClient bound to the imported app with patched behaviors
    to avoid startup side effects.
    """
    api = import_api

    # Ensure auto update disabled inside runtime even if checking function runs
    monkeypatch.setenv("LM_BRIDGE_DISABLE_AUTO_UPDATE", "1")

    # Speed up stream timeout for tests
    api.CONFIG["stream_response_timeout_seconds"] = 1

    # Use TestClient (sync) to drive the FastAPI app with lifespan support
    cl = TestClient(api.app)
    return cl

# --- Tests for pure/helper functions ---


def test_load_config_jsonc_comments_removed(import_api, monkeypatch, tmp_path):
    api = import_api
    # Overwrite config with jsonc including comments and ensure parsed
    cfg = tmp_path / "config.jsonc"
    cfg.write_text(
        """
        {
          // single-line
          "a": "1",
          /* block
             comment */
          "b": "2"
        }
        """,
        encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    api.load_config()
    assert api.CONFIG.get("a") == "1"
    assert api.CONFIG.get("b") == "2"

def test_load_model_endpoint_map_missing_file(import_api, monkeypatch, tmp_path, caplog):
    api = import_api
    # Remove file to simulate missing
    p = tmp_path / "model_endpoint_map.json"
    if p.exists():
        p.unlink()
    monkeypatch.chdir(tmp_path)
    api.load_model_endpoint_map()
    assert api.MODEL_ENDPOINT_MAP == {}
    assert any("未找到" in rec.message for rec in caplog.records if rec.levelname in ("WARNING","ERROR"))

def test_extract_models_from_html_parses_escaped_json(import_api):
    api = import_api
    # Construct escaped JSON sequences inside HTML-like content
    model1 = {
        "id": "11111111-1111-1111-1111-111111111111",
        "publicName": "Model One",
        "other": {"x": 1}
    }
    model2 = {
        "id": "22222222-2222-2222-2222-222222222222",
        "publicName": "Model Two",
        "other": {"y": 2}
    }
    def esc(obj):
        s = json.dumps(obj, ensure_ascii=False)
        return s.replace('"','\\"').replace('\\', '\\\\')
    html = f"""
    <html>
    <body>
    <script>
    var x = "{esc(model1)}"; var y = "{esc(model2)}";
    // Or embedded JSON directly:
    {esc(model1)}
    {esc(model2)}
    </script>
    </body>
    </html>
    """
    res = api.extract_models_from_html(html)
    assert isinstance(res, list)
    names = sorted([m.get("publicName") for m in res])
    assert names == ["Model One", "Model Two"]

def test_extract_models_from_html_dedup_by_public_name(import_api):
    api = import_api
    m = {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeffffffff", "publicName": "Same", "k": 1}
    # Duplicate with same publicName should be deduped
    html = (json.dumps(m).replace('"','\\"').replace('\\','\\\\')) * 2
    res = api.extract_models_from_html(html)
    assert len(res) == 1
    assert res[0]["publicName"] == "Same"

def test_save_available_models_writes_file(import_api, tmp_path):
    api = import_api
    p = tmp_path / "avail.json"
    models = [{"id":"1","publicName":"A"},{"id":"2","publicName":"B"}]
    api.save_available_models(models, models_path=str(p))
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded == models

def test__process_openai_message_text_and_images_with_detail_filename(import_api):
    api = import_api
    # Message with list content including text and data URL image; provide detail for filename
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {
                "url": "data:image/png;base64,AAAA",
                "detail": "original.png"
            }},
            {"type": "image_url", "image_url": {
                "url": "data:audio/mp3;base64,BBBB",
                # no detail; will trigger generated name
            }},
        ]
    }
    out = api._process_openai_message(msg)
    assert out["role"] == "user"
    assert out["content"] == "Hello"
    assert len(out["attachments"]) == 2
    assert out["attachments"][0]["name"] == "original.png"
    assert out["attachments"][0]["contentType"] == "image/png"
    # Second attachment gets a generated prefix based on contentType
    assert out["attachments"][1]["contentType"] == "audio/mp3"
    assert out["attachments"][1]["name"].startswith("audio_")
    assert out["attachments"][1]["name"].endswith(".mp3")

def test__process_openai_message_user_empty_text_becomes_space(import_api):
    api = import_api
    msg = {"role": "user", "content": "   "}
    out = api._process_openai_message(msg)
    assert out["content"] == " "

def test_convert_openai_to_lmarena_payload_modes_and_positions(import_api, monkeypatch):
    api = import_api
    # Base config: direct_chat, no tavern, no bypass
    api.CONFIG.update({
        "tavern_mode_enabled": False,
        "bypass_enabled": False,
        "id_updater_last_mode": "direct_chat",
        "id_updater_battle_target": "A",
    })
    # Provide a mapping for model ID lookup
    api.MODEL_NAME_TO_ID_MAP.clear()
    api.MODEL_NAME_TO_ID_MAP.update({"test-model": "model-id-123"})

    messages = [
        {"role":"system","content":"S1"},
        {"role":"developer","content":"Dev becomes system"},
        {"role":"user","content":"Hi"}
    ]
    payload = api.convert_openai_to_lmarena_payload(
        {"model":"test-model","messages":messages},
        session_id="SID",
        message_id="MID"
    )
    # developer normalized to system, system in direct chat -> participantPosition 'b'
    roles = [m["role"] for m in payload["message_templates"]]
    positions = [m["participantPosition"] for m in payload["message_templates"]]
    assert roles == ["system","system","user"]
    assert positions == ["b","b","a"]  # system->b, user->a in direct_chat
    assert payload["target_model_id"] == "model-id-123"

def test_convert_openai_to_lmarena_payload_tavern_merges_system(import_api):
    api = import_api
    api.CONFIG.update({
        "tavern_mode_enabled": True,
        "bypass_enabled": False,
        "id_updater_last_mode": "direct_chat",
    })
    messages = [
        {"role":"system","content":"S1"},
        {"role":"system","content":"S2"},
        {"role":"user","content":"Hi"}
    ]
    payload = api.convert_openai_to_lmarena_payload(
        {"model":"unknown-model","messages":messages},
        session_id="SID",
        message_id="MID"
    )
    mts = payload["message_templates"]
    assert mts[0]["role"] == "system"
    assert mts[0]["content"] == "S1\n\nS2"
    assert mts[0]["attachments"] == []
    assert mts[0]["participantPosition"] == "b"  # still direct_chat for system
    assert mts[1]["role"] == "user"
    assert mts[1]["participantPosition"] == "a"

def test_convert_openai_to_lmarena_payload_bypass_adds_position_a(import_api):
    api = import_api
    api.CONFIG.update({
        "tavern_mode_enabled": False,
        "bypass_enabled": True,
        "id_updater_last_mode": "direct_chat",
    })
    payload = api.convert_openai_to_lmarena_payload(
        {"model":"unknown","messages":[{"role":"user","content":"Hi"}]},
        session_id="SID", message_id="MID"
    )
    # Additional user message with content " " and participantPosition 'a'
    assert payload["message_templates"][-1] == {"role":"user","content":" ","participantPosition":"a","attachments":[]}

@pytest.mark.anyio
async def test__process_lmarena_stream_normal_flow(import_api, monkeypatch):
    api = import_api
    q = asyncio.Queue()
    rid = "req-1"
    api.response_channels[rid] = q

    # Put content lines emulating 'a0:"Text"' pattern and a finish pattern, then [DONE]
    await q.put('a0:"Hello"')
    await q.put('bd:{"finishReason":"stop"}')
    await q.put("[DONE]")

    events = []
    async for typ, data in api._process_lmarena_stream(rid):
        events.append((typ, data))
    # Should yield one content and one finish
    assert ('content','Hello') in events
    assert ('finish','stop') in events
    # Channel cleaned
    assert rid not in api.response_channels

@pytest.mark.anyio
async def test__process_lmarena_stream_413_error_friendly(import_api):
    api = import_api
    q = asyncio.Queue()
    rid = "rid-413"
    api.response_channels[rid] = q
    await q.put({"error": "413 Payload Too Large"})
    events = []
    async for typ, data in api._process_lmarena_stream(rid):
        events.append((typ, data))
    assert events and events[0][0] == 'error'
    assert "附件大小超过了" in events[0][1]

@pytest.mark.anyio
async def test__process_lmarena_stream_cloudflare_triggers_refresh(import_api, monkeypatch):
    api = import_api
    q = asyncio.Queue()
    rid = "rid-cf"
    api.response_channels[rid] = q
    await q.put('<title>Just a moment...</title>')

    dummy_ws = DummyWS()
    api.browser_ws = dummy_ws
    # Provide event loop for run_coroutine_threadsafe usage in restart (not used here)
    api.main_event_loop = asyncio.get_running_loop()

    events = []
    async for typ, data in api._process_lmarena_stream(rid):
        events.append((typ, data))
    assert events and events[0][0] == 'error'
    assert "Cloudflare" in events[0][1]
    # Ensure refresh command was attempted
    assert any('"refresh"' in s for s in dummy_ws.sent_texts)

def test_format_openai_helpers(import_api):
    api = import_api
    s = api.format_openai_chunk("x", "m", "id")
    assert s.startswith("data: ")
    assert '"delta": {"content": "x"}' in s

    s2 = api.format_openai_finish_chunk("m", "id", reason="stop")
    assert "data: [DONE]" in s2

    err = api.format_openai_error_chunk("oops", "m", "id")
    assert "[LMArena Bridge Error]" in err

    non_stream = api.format_openai_non_stream_response("hello", "m", "id", "stop")
    assert non_stream["object"] == "chat.completion"
    assert non_stream["choices"][0]["message"]["content"] == "hello"

# --- Endpoint tests (via TestClient) ---


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["time"].endswith("Z")

def test_get_models_404_when_empty(import_api, client, monkeypatch):
    api = import_api
    api.MODEL_NAME_TO_ID_MAP.clear()
    resp = client.get("/v1/models")
    assert resp.status_code == 404
    data = resp.json()
    assert "模型列表为空" in data["error"]

def test_get_models_lists_models(import_api, client):
    api = import_api
    api.MODEL_NAME_TO_ID_MAP.clear()
    api.MODEL_NAME_TO_ID_MAP.update({"m1":"id1","m2":"id2"})
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    ids = {m["id"] for m in data["data"]}
    assert ids == {"m1","m2"}

def test_request_model_update_requires_browser(import_api, client):
    api = import_api
    api.browser_ws = None
    resp = client.post("/internal/request_model_update")
    assert resp.status_code == 503

def test_request_model_update_sends_command(import_api, client):
    api = import_api
    dummy = DummyWS()
    api.browser_ws = dummy
    resp = client.post("/internal/request_model_update")
    assert resp.status_code == 200
    assert any('"send_page_source"' in s for s in dummy.sent_texts)

def test_update_available_models_no_body(import_api, client):
    resp = client.post("/internal/update_available_models", content=b"")
    assert resp.status_code == 400
    body = resp.json()
    assert body["message"] == "No HTML content received."

def test_update_available_models_success(import_api, client, tmp_path, monkeypatch):
    model = {"id":"123","publicName":"X"}
    esc = json.dumps(model).replace('"','\\"').replace('\\','\\\\')
    html = f"<html>{esc}</html>"
    resp = client.post("/internal/update_available_models", content=html.encode("utf-8"))
    assert resp.status_code == 200
    out = resp.json()
    assert out["status"] == "success"
    # ensure file updated
    p = tmp_path / "available_models.json"
    assert p.exists()
    js = json.loads(p.read_text(encoding="utf-8"))
    assert js and js[0]["publicName"] == "X"

def test_start_id_capture_requires_browser(import_api, client):
    api = import_api
    api.browser_ws = None
    resp = client.post("/internal/start_id_capture")
    assert resp.status_code == 503

def test_start_id_capture_sends_command(import_api, client):
    api = import_api
    dummy = DummyWS()
    api.browser_ws = dummy
    resp = client.post("/internal/start_id_capture")
    assert resp.status_code == 200
    assert any('"activate_id_capture"' in s for s in dummy.sent_texts)

def test_chat_completions_requires_auth_when_config_api_key(import_api, client):
    # Missing Authorization header
    payload = {"model":"test-model","messages":[{"role":"user","content":"Hi"}], "stream": False}
    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 401

def test_chat_completions_503_when_no_browser(import_api, client):
    api = import_api
    api.browser_ws = None
    headers = {"Authorization": "Bearer secret-key"}
    payload = {"model":"test-model","messages":[{"role":"user","content":"Hi"}], "stream": False}
    resp = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert resp.status_code == 503

def test_chat_completions_400_on_invalid_session_ids(import_api, client, monkeypatch):
    api = import_api
    # Configure browser_ws so early checks pass
    api.browser_ws = DummyWS()
    # Force CONFIG to invalid session/message IDs
    api.CONFIG["session_id"] = "YOUR_SESSION"
    api.CONFIG["message_id"] = "YOUR_MESSAGE"
    headers = {"Authorization": "Bearer secret-key"}
    payload = {"model":"unknown-model","messages":[{"role":"user","content":"Hi"}], "stream": False}
    resp = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert resp.status_code == 400
    assert "无效" in resp.json()["detail"]

def test_chat_completions_non_stream_success_with_defaults(import_api, client, monkeypatch):
    api = import_api
    # Valid global IDs
    api.CONFIG["session_id"] = "SESSION_OK"
    api.CONFIG["message_id"] = "MESSAGE_OK"
    api.browser_ws = DummyWS()

    # Patch _process_lmarena_stream to yield simple content then finish then done
    async def fake_stream(request_id: str):
        yield 'content', 'Hello '
        yield 'content', 'World'
        yield 'finish', 'stop'
    monkeypatch.setattr(api, "_process_lmarena_stream", fake_stream)

    headers = {"Authorization": "Bearer secret-key"}
    payload = {"model":"test-model","messages":[{"role":"user","content":"Hi"}], "stream": False}
    resp = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "Hello World"

def test_chat_completions_stream_success_basic(import_api, client, monkeypatch):
    api = import_api
    api.CONFIG["session_id"] = "SESSION_OK"
    api.CONFIG["message_id"] = "MESSAGE_OK"
    api.browser_ws = DummyWS()

    async def fake_stream(request_id: str):
        yield 'content', 'A'
        yield 'content', 'B'
        yield 'finish', 'stop'
    monkeypatch.setattr(api, "_process_lmarena_stream", fake_stream)

    headers = {"Authorization": "Bearer secret-key"}
    payload = {"model":"test-model","messages":[{"role":"user","content":"Hi"}], "stream": True}
    with client.stream("POST", "/v1/chat/completions", json=payload, headers=headers) as r:
        assert r.status_code == 200
        chunks = b"".join(r.iter_bytes())
    # Should contain two chunks with "A" and "B" and a finish [DONE]
    s = chunks.decode("utf-8", errors="ignore")
    assert '"delta": {"content": "A"}' in s
    assert '"delta": {"content": "B"}' in s
    assert "data: [DONE]" in s

def test_images_generations_delegates_to_module(import_api, client, monkeypatch):
    api = import_api
    api.browser_ws = DummyWS()
    headers = {"Authorization": "Bearer secret-key"}
    resp = client.post("/v1/images/generations", json={"prompt":"a cat"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "via": "stub"}