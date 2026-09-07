"""Tests for the MCP client, and above all for its deadline.

WHY THIS FILE EXISTS. On the morning of 2026-09-07 IB Gateway lost its upstream
connection to IBKR. The MCP server kept every HTTP response open while it waited
on Gateway, so the client's timeout, which was only a socket read timeout, never
fired: one portfolio() call made with timeout=60 ran for 1,240 seconds. The tick
that started at 07:37 New York finished at 09:25, and every one minute pre-open
wake up in between was lost because launchd will not start a second copy of a job
that is still running.

So the tests below run a real HTTP server that accepts the request, sends the
headers, and then dribbles keepalive bytes forever without ever finishing the
body. That is the shape of the failure, and the client has to give up on it
inside its timeout.

Nothing here talks to IB Gateway, the real MCP server or the network beyond
127.0.0.1 on a port the operating system picks.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_mcp_client.py -q
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import mcp_client as mcp  # noqa: E402

#: Short on purpose. Every test here waits out a real deadline, so the suite
#: pays for this number twice over.
TIMEOUT = 2.0

#: What the task is: a call must be back within its timeout plus one second.
SLACK = 1.0


# --------------------------------------------------------------- the fake server

class Handler(BaseHTTPRequestHandler):
    """Answers the handshake, then behaves however the test asked it to.

    `server.hang_on` is the set of JSON-RPC methods that get the 2026-09-07
    treatment: headers, then keepalive comment lines forever, never an end.
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):        # noqa: D102 - quiet, pytest is noisy enough
        pass

    def _read_message(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                   # noqa: N802 - the name BaseHTTPRequestHandler wants
        message = self._read_message()
        method = message.get("method", "")
        msg_id = message.get("id")
        self.server.seen.append(method)

        if method in self.server.hang_on:
            self.dribble_forever()
            return

        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if method == "initialize":
            self._send_json({"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": mcp.PROTOCOL_VERSION,
                "serverInfo": {"name": "fake-ibkr", "version": "0.0"}}})
            return

        if method == "tools/call":
            self._send_json({"jsonrpc": "2.0", "id": msg_id, "result": {
                "structuredContent": {"account": "DUT077572", "positions": []}}})
            return

        self._send_json({"jsonrpc": "2.0", "id": msg_id, "result": {}})

    def dribble_forever(self) -> None:
        """The failure of 2026-09-07: alive, talking, and never finished.

        Server sent events with no length, a comment line every tenth of a
        second. Nothing here is ever silent for long enough for a socket read
        timeout to notice, and the body never ends.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        while not self.server.stopping.is_set():
            try:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
            except Exception:            # noqa: BLE001 - the client hung up, which is the point
                return
            time.sleep(0.1)


class FakeServer:
    """A one line context manager around the handler above."""

    def __init__(self, hang_on: tuple[str, ...] = ()) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.hang_on = set(hang_on)
        self.httpd.seen = []
        self.httpd.stopping = threading.Event()
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/mcp"

    @property
    def seen(self) -> list:
        return self.httpd.seen

    def __enter__(self) -> "FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.stopping.set()
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def hangs_on_everything():
    with FakeServer(hang_on=("initialize", "tools/call")) as server:
        yield server


@pytest.fixture
def hangs_on_the_tool_call():
    with FakeServer(hang_on=("tools/call",)) as server:
        yield server


@pytest.fixture
def healthy():
    with FakeServer() as server:
        yield server


# ------------------------------------------------------------------ the deadline

def test_a_server_that_never_finishes_the_body_is_given_up_on_in_time(
        hangs_on_everything):
    """The 1,240 second call, in miniature. Two seconds means two seconds."""
    client = mcp.McpClient(url=hangs_on_everything.url, timeout=TIMEOUT)
    began = time.monotonic()
    with pytest.raises(mcp.McpError) as caught:
        client.initialize()
    spent = time.monotonic() - began
    assert spent < TIMEOUT + SLACK, f"gave up after {spent:.1f} seconds"
    assert spent >= TIMEOUT - 0.5, "gave up before its own timeout was up"
    assert "took longer than 2 seconds" in str(caught.value)


def test_a_tool_call_that_hangs_after_the_handshake_still_comes_back(
        hangs_on_the_tool_call):
    """The real shape: the server answers fine until it has to ask Gateway."""
    client = mcp.McpClient(url=hangs_on_the_tool_call.url, timeout=TIMEOUT)
    began = time.monotonic()
    with pytest.raises(mcp.McpError) as caught:
        client.portfolio()
    spent = time.monotonic() - began
    assert spent < TIMEOUT + SLACK, f"portfolio() ran for {spent:.1f} seconds"
    assert "took longer than 2 seconds" in str(caught.value)
    assert "tools/call" in str(caught.value)
    # The handshake did happen, so this is the tool call giving up and not the
    # client failing to connect at all.
    assert "initialize" in hangs_on_the_tool_call.seen


def test_the_wording_is_the_one_the_loop_logs(hangs_on_everything):
    """agent/loop.py prints this sentence as it stands. Keep it that way."""
    client = mcp.McpClient(url=hangs_on_everything.url, timeout=TIMEOUT)
    with pytest.raises(mcp.McpError) as caught:
        client.account_values()
    message = str(caught.value)
    assert message.startswith("the MCP server took longer than")
    assert "IB Gateway is usually the slow part" in message


def test_the_handshake_and_the_tool_call_share_one_budget(hangs_on_the_tool_call):
    """A first call does the handshake too, and still fits inside the timeout."""
    client = mcp.McpClient(url=hangs_on_the_tool_call.url, timeout=TIMEOUT)
    began = time.monotonic()
    with pytest.raises(mcp.McpError):
        client.open_orders()
    assert time.monotonic() - began < TIMEOUT + SLACK


def test_a_hung_call_leaves_the_client_usable(hangs_on_the_tool_call, healthy):
    """Giving up must not poison the client for the next tick."""
    client = mcp.McpClient(url=hangs_on_the_tool_call.url, timeout=TIMEOUT)
    with pytest.raises(mcp.McpError):
        client.portfolio()
    client.url = healthy.url
    client._ready = False
    assert client.portfolio() == {"account": "DUT077572", "positions": []}


def test_is_up_says_no_rather_than_hanging(hangs_on_everything):
    client = mcp.McpClient(url=hangs_on_everything.url, timeout=TIMEOUT)
    began = time.monotonic()
    assert client.is_up() is False
    assert time.monotonic() - began < TIMEOUT + SLACK


# ------------------------------------------------- the ordinary path still works

def test_a_normal_answer_comes_back_as_before(healthy):
    client = mcp.McpClient(url=healthy.url, timeout=TIMEOUT)
    info = client.initialize()
    assert info == {"name": "fake-ibkr", "version": "0.0"}
    assert client.portfolio() == {"account": "DUT077572", "positions": []}
    assert healthy.seen[:2] == ["initialize", "notifications/initialized"]


def test_nothing_reachable_is_still_a_clear_error():
    """Port 1 has nothing on it, and the message has to say what to start."""
    client = mcp.McpClient(url="http://127.0.0.1:1/mcp", timeout=TIMEOUT)
    with pytest.raises(mcp.McpError) as caught:
        client.initialize()
    assert "cannot reach the MCP server" in str(caught.value)


def test_a_budget_already_spent_gives_up_without_asking(healthy):
    """A deadline in the past means no round trip at all, not one more wait."""
    client = mcp.McpClient(url=healthy.url, timeout=TIMEOUT)
    client._deadline = time.monotonic() - 1.0
    with pytest.raises(mcp.McpError) as caught:
        client.list_tools()
    assert "took longer than" in str(caught.value)
    assert healthy.seen == []
