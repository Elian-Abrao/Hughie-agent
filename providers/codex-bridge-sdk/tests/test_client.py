from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib import error

from codex_bridge_sdk import BridgeClientError, BridgeHttpError, CodexBridgeClient


class FakeResponse:
    def __init__(self, *, body: str = "", lines: list[bytes] | None = None) -> None:
        self._body = body.encode("utf-8")
        self._lines = list(lines or [])
        self.closed = False

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True

    def __iter__(self):
        return iter(self._lines)


class CodexBridgeClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = CodexBridgeClient("http://127.0.0.1:47831")

    def test_health_uses_expected_endpoint(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["timeout"] = timeout
            return FakeResponse(body='{"ok": true, "service": "codex-bridge"}')

        with patch("codex_bridge_sdk.client.request.urlopen", side_effect=fake_urlopen):
            payload = self.client.health()

        self.assertTrue(payload["ok"])
        self.assertEqual(captured["url"], "http://127.0.0.1:47831/v1/health")
        self.assertEqual(captured["method"], "GET")

    def test_complete_login_posts_redirect_url(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["body"] = req.data.decode("utf-8") if req.data else ""
            return FakeResponse(body='{"session": {"email": "user@example.com"}}')

        with patch("codex_bridge_sdk.client.request.urlopen", side_effect=fake_urlopen):
            response = self.client.complete_login(
                "http://localhost:1455/auth/callback?code=abc&state=def"
            )

        self.assertEqual(captured["url"], "http://127.0.0.1:47831/v1/auth/complete")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            json.loads(str(captured["body"])),
            {"redirectUrl": "http://localhost:1455/auth/callback?code=abc&state=def"},
        )
        self.assertEqual(response["session"]["email"], "user@example.com")

    def test_create_agent_session_posts_expected_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["body"] = req.data.decode("utf-8") if req.data else ""
            return FakeResponse(body='{"session":{"id":"sess-1","approvalPolicy":"manual"}}')

        with patch("codex_bridge_sdk.client.request.urlopen", side_effect=fake_urlopen):
            response = self.client.create_agent_session(
                {"permissionProfile": "read-only", "approvalPolicy": "manual"}
            )

        self.assertEqual(captured["url"], "http://127.0.0.1:47831/v1/agent/sessions")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            json.loads(str(captured["body"])),
            {"permissionProfile": "read-only", "approvalPolicy": "manual"},
        )
        self.assertEqual(response["session"]["id"], "sess-1")

    def test_approve_agent_action_uses_expected_route(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            return FakeResponse(body='{"session":{"id":"sess-1"},"events":[]}')

        with patch("codex_bridge_sdk.client.request.urlopen", side_effect=fake_urlopen):
            response = self.client.approve_agent_action("sess-1", "action-1")

        self.assertEqual(
            captured["url"],
            "http://127.0.0.1:47831/v1/agent/sessions/sess-1/actions/action-1/approve",
        )
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(response["session"]["id"], "sess-1")

    def test_http_errors_raise_bridge_http_error(self) -> None:
        http_error = error.HTTPError(
            url="http://127.0.0.1:47831/chat",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"Instructions are required"}'),
        )

        with patch("codex_bridge_sdk.client.request.urlopen", side_effect=http_error):
            with self.assertRaises(BridgeHttpError) as ctx:
                self.client.chat({"messages": [{"role": "user", "content": "Oi"}]})

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(str(ctx.exception), "Instructions are required")
        self.assertEqual(ctx.exception.body, '{"error":"Instructions are required"}')

    def test_stream_chat_aggregates_deltas(self) -> None:
        events = iter(
            [
                {
                    "requestId": "req-1",
                    "provider": "codex",
                    "kind": "status",
                    "message": "Connecting",
                },
                {
                    "requestId": "req-1",
                    "provider": "codex",
                    "kind": "delta",
                    "delta": "Ol",
                },
                {
                    "requestId": "req-1",
                    "provider": "codex",
                    "kind": "delta",
                    "delta": "a",
                },
                {
                    "requestId": "req-1",
                    "provider": "codex",
                    "kind": "done",
                },
            ]
        )
        seen: list[dict[str, object]] = []

        with patch.object(CodexBridgeClient, "iter_stream_chat", return_value=events):
            response = self.client.stream_chat(
                {"model": "gpt-5.4", "messages": [{"role": "user", "content": "Oi"}]},
                on_event=seen.append,
            )

        self.assertEqual(response["requestId"], "req-1")
        self.assertEqual(response["provider"], "codex")
        self.assertEqual(response["model"], "gpt-5.4")
        self.assertEqual(response["outputText"], "Ola")
        self.assertEqual(len(seen), 4)

    def test_iter_stream_chat_parses_sse_payload(self) -> None:
        response = FakeResponse(
            lines=[
                b"event: message\n",
                b'data: {"requestId":"req-2","provider":"codex","kind":"status","message":"Connecting"}\n',
                b"\n",
                b'data: {"requestId":"req-2","provider":"codex","kind":"delta","delta":"Oi"}\n',
                b"\n",
                b'data: {"requestId":"req-2","provider":"codex","kind":"done"}\n',
                b"\n",
            ]
        )

        with patch("codex_bridge_sdk.client.request.urlopen", return_value=response):
            events = list(
                self.client.iter_stream_chat(
                    {"messages": [{"role": "user", "content": "Oi"}]}
                )
            )

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["kind"], "status")
        self.assertEqual(events[1]["delta"], "Oi")
        self.assertEqual(events[2]["kind"], "done")
        self.assertTrue(response.closed)

    def test_iter_stream_chat_rejects_malformed_payload(self) -> None:
        response = FakeResponse(lines=[b"data: not-json\n", b"\n"])

        with patch("codex_bridge_sdk.client.request.urlopen", return_value=response):
            with self.assertRaises(BridgeClientError) as ctx:
                list(
                    self.client.iter_stream_chat(
                        {"messages": [{"role": "user", "content": "Oi"}]}
                    )
                )

        self.assertIn("malformed event", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
