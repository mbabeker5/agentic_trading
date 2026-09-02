"""Small client for the local IBKR MCP server.

The server is patrickpxp/ibkr-mcp-server, started by
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_mcp.sh
and listening on http://127.0.0.1:8765/mcp over "streamable HTTP".

Why this file exists at all: the trading loop is a plain Python script run by
launchd every five minutes, not a chat session, so it cannot use Claude Code's
MCP plumbing. It has to speak the protocol itself. The protocol is only three
messages deep, so this is a short file rather than a dependency.

Deliberately READ ONLY. Every method here fetches information: account values,
positions, orders, fills, quotes, price history. Nothing here can move money.

The order tools the server also offers (ibkr_place_order, ibkr_bracket_order,
ibkr_preview_order, ibkr_cancel_order, ibkr_global_cancel, ibkr_oca_group,
ibkr_exercise_options) are deliberately NOT wrapped. That is not an oversight
and it is not a gap to fill in passing. The live order path will be added here
behind the guardrail layer in agent/guardrails.py, and only once Mo has read
the strategy numbers and said yes. Until then the loop can look at the market
all it likes and cannot touch it.

Uses only the Python standard library, so it keeps working even if the venv
loses a package.

Self test (reads only, places nothing):

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/mcp_client.py
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_TIMEOUT = 45.0

# The version of the MCP spec we ask for. The server answered with this on
# 2026-09-02, so we are speaking the same dialect it is.
PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """Anything that went wrong talking to the MCP server.

    The message is written to be readable in a log file at 9:35 in the morning,
    not to be pretty.
    """


def _parse_body(raw: str, content_type: str, want_id: int | None) -> dict:
    """Turn one HTTP response body into one JSON-RPC message.

    The server may answer in either of two shapes, and which one it picks is
    its business, so we handle both:

    * plain JSON, one object, which is what it does today; or
    * server sent events, a stream of lines where the ones we want start with
      "data:" and hold the JSON. Comment lines start with ":" and event type
      lines start with "event:"; both are noise to us.
    """
    text = raw.strip()
    looks_like_sse = "text/event-stream" in content_type.lower() or text.startswith(
        ("event:", "data:", ":")
    )

    if not looks_like_sse:
        if not text:
            raise McpError("the MCP server sent an empty reply")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpError(
                f"the MCP server sent something that is not JSON: {text[:200]!r}"
            ) from exc

    messages: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            messages.append(json.loads(payload))
        except json.JSONDecodeError:
            # A partial or non JSON data line. Skip it rather than dying, the
            # message we want is usually the next one.
            continue

    if not messages:
        raise McpError(
            f"the MCP server sent an event stream with no usable data lines: {text[:200]!r}"
        )
    if want_id is not None:
        for msg in messages:
            if msg.get("id") == want_id:
                return msg
    for msg in messages:
        if "result" in msg or "error" in msg:
            return msg
    return messages[-1]


class McpClient:
    """One conversation with the IBKR MCP server.

    Create it, call a method, read the answer. It connects lazily on the first
    call, so building one costs nothing.
    """

    def __init__(self, url: str = DEFAULT_URL, timeout: float = DEFAULT_TIMEOUT,
                 account: str | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self.account = account
        self._session_id: str | None = None
        self._next_id = 0
        self._ready = False
        self.server_info: dict = {}

    # ---------------------------------------------------------------- plumbing

    def _rpc(self, method: str, params: dict | None = None,
             notification: bool = False) -> Any:
        """Send one JSON-RPC message and return its result.

        A notification has no id and gets no answer, which is what the spec
        wants for notifications/initialized.
        """
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        msg_id: int | None = None
        if not notification:
            self._next_id += 1
            msg_id = self._next_id
            body["id"] = msg_id

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        # The server is stateless today and hands out no session id. If a later
        # version starts doing so, we pick it up from the first reply and send
        # it back on every message after that, which is what the spec asks for.
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"),
            headers=headers, method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300] if exc.fp else ""
            if exc.code == 404 and self._session_id:
                # The server forgot our session. Drop it so the next call
                # starts a fresh one instead of looping on a dead id.
                self._session_id = None
                self._ready = False
            raise McpError(
                f"the MCP server refused {method} with HTTP {exc.code} {exc.reason}. {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise McpError(
                f"cannot reach the MCP server at {self.url} ({exc.reason}). "
                "Is it running? Start it with "
                "/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_mcp.sh"
            ) from exc
        except socket.timeout as exc:
            raise McpError(
                f"the MCP server took longer than {self.timeout:.0f} seconds to answer {method}. "
                "IB Gateway is usually the slow part when this happens."
            ) from exc

        if notification:
            # 202 with an empty body is the normal, correct answer here.
            return None

        if status == 202 and not raw.strip():
            raise McpError(f"the MCP server accepted {method} but sent no answer back")

        message = _parse_body(raw, content_type, msg_id)
        if "error" in message and message["error"]:
            err = message["error"]
            raise McpError(
                f"the MCP server reported an error on {method}: "
                f"{err.get('message', err)} (code {err.get('code')})"
            )
        if "result" not in message:
            raise McpError(f"the MCP server answered {method} without a result: {message}")
        return message["result"]

    def initialize(self) -> dict:
        """Do the opening handshake. Safe to call more than once."""
        if self._ready:
            return self.server_info
        result = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "agentic-trading-loop", "version": "0.1"},
        })
        self.server_info = result.get("serverInfo", {}) or {}
        # The spec wants this notification before any real work. Without it a
        # stricter server is entitled to reject every tool call.
        self._rpc("notifications/initialized", notification=True)
        self._ready = True
        return self.server_info

    def list_tools(self) -> list[dict]:
        """Every tool the server offers, as the server describes them."""
        self.initialize()
        return self._rpc("tools/list", {}).get("tools", [])

    def tool_names(self) -> list[str]:
        return [t.get("name", "") for t in self.list_tools()]

    def call(self, name: str, arguments: dict | None = None) -> Any:
        """Call one tool and hand back its answer in the most useful form.

        Prefers structuredContent, which is already parsed. Falls back to the
        text block, parsed as JSON when it is JSON and left as a string when
        it is not.

        Raises McpError when the tool reports a failure, so a caller cannot
        quietly carry on with a half answer.
        """
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

        blocks = result.get("content") or []
        texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        joined = "\n".join(t for t in texts if t)

        if result.get("isError"):
            raise McpError(f"the tool {name} failed: {joined[:500] or result}")

        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        if not joined:
            return None
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return joined

    def is_up(self) -> bool:
        """True when the server answers a handshake. Never raises."""
        try:
            self.initialize()
            return True
        except McpError:
            return False

    # ------------------------------------------------------------- read tools

    def account_summary(self, account: str | None = None) -> dict:
        """Account values: NetLiquidation, BuyingPower, cash, margin and so on.

        Comes back as {"account": "DU...", "items": [{"tag", "value", ...}, ...]}.
        Use account_values() below if you just want a number by name.
        """
        return self.call("ibkr_get_account_summary",
                         {"account": account or self.account})

    def account_values(self, account: str | None = None) -> dict[str, str]:
        """The same thing as a plain {tag: value} lookup, which is easier to read."""
        summary = self.account_summary(account) or {}
        return {item.get("tag"): item.get("value")
                for item in summary.get("items", [])
                if isinstance(item, dict) and item.get("tag")}

    def portfolio(self, account: str | None = None, include_pnl: bool = True) -> dict:
        """Open positions with market value and profit so far.

        Comes back as {"account", "positions": [...], "totals": {...}, "notes": [...]}
        where each position has symbol, secType, exchange, currency, conId,
        position, avgCost, marketPrice, marketValue, unrealizedPnl, realizedPnl.
        """
        return self.call("ibkr_get_portfolio",
                         {"account": account or self.account, "include_pnl": include_pnl})

    def open_orders(self, account: str | None = None, include_all: bool = True) -> dict:
        """Orders that are still working. Comes back as {"orders": [...], "notes": [...]}."""
        return self.call("ibkr_get_open_orders",
                         {"account": account or self.account, "include_all": include_all})

    def executions(self, account: str | None = None, symbol: str | None = None,
                   sec_type: str | None = None, exchange: str | None = None,
                   side: str | None = None, time: str | None = None) -> dict:
        """Fills. This is the honest answer to "what do we actually own".

        Worth knowing: the server has a bug where a market order that fills
        instantly comes back as an error even though it filled. That is why the
        rule is to confirm every order against executions() and open_orders()
        rather than trusting the order call's own answer.
        """
        args = {"account": account or self.account, "symbol": symbol,
                "secType": sec_type, "exchange": exchange, "side": side, "time": time}
        return self.call("ibkr_get_executions", args)

    def snapshot(self, contracts: list[dict], market_data_type: int = 3) -> dict:
        """One shot quotes for a list of contracts.

        market_data_type 1 is live and 3 is delayed. The default is 3 because
        the paper account has no live data subscription yet, and a delayed
        quote that arrives beats a live one that does not.

        A contract is a plain object in IBKR's own words, for example
        {"symbol": "SPY", "secType": "STK", "exchange": "SMART", "currency": "USD"}.
        """
        return self.call("ibkr_get_market_data_snapshot", {
            "contracts": contracts,
            "market_data_type": market_data_type,
            "regulatory_snapshot": False,
        })

    def historical_bars(self, contract: dict, duration: str, bar_size: str,
                        what: str = "TRADES", use_rth: bool = True,
                        end_date_time: str = "") -> dict:
        """Price history for one contract.

        duration is IBKR's phrasing, "1 D" or "2 W". bar_size is "5 mins" or
        "1 hour". An empty end_date_time means "up to now".

        Comes back as {"bars": [...], "notes": [...]} where each bar has time,
        open, high, low, close, volume, average and barCount. The average field
        is that bar's volume weighted average price, which is what the fade
        rule in the strategy is built on.
        """
        return self.call("ibkr_get_historical_bars", {
            "contract": contract,
            "endDateTime": end_date_time,
            "durationStr": duration,
            "barSizeSetting": bar_size,
            "whatToShow": what,
            "useRTH": use_rth,
            "formatDate": 1,
        })

    def bars_5m_today(self, contract: dict) -> list[dict]:
        """Shortcut: today's five minute bars, regular hours only, as a list."""
        answer = self.historical_bars(contract, "1 D", "5 mins") or {}
        return answer.get("bars", []) or []


def session_vwap(bars: list[dict]) -> float | None:
    """The day's volume weighted average price from a list of five minute bars.

    Each bar already carries its own average price, so weighting those by each
    bar's volume gives the session figure. Returns None when there is nothing
    to average, which happens before the open and on a holiday.
    """
    total_value = 0.0
    total_volume = 0.0
    for bar in bars:
        volume = bar.get("volume") or 0.0
        price = bar.get("average")
        if price is None:
            high, low, close = bar.get("high"), bar.get("low"), bar.get("close")
            if None in (high, low, close):
                continue
            price = (high + low + close) / 3.0
        if volume <= 0:
            continue
        total_value += float(price) * float(volume)
        total_volume += float(volume)
    if total_volume <= 0:
        return None
    return total_value / total_volume


def _self_test() -> int:
    """Read a few things and print them. Places nothing, cancels nothing."""
    client = McpClient()
    try:
        info = client.initialize()
    except McpError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"connected to {info.get('name')} version {info.get('version')} at {client.url}")

    names = client.tool_names()
    print(f"tools offered: {len(names)}")

    values = client.account_values()
    print(f"account: net liquidation {values.get('NetLiquidation')}, "
          f"cash {values.get('TotalCashValue')}, buying power {values.get('BuyingPower')}")

    holdings = client.portfolio() or {}
    positions = holdings.get("positions", [])
    print(f"account id {holdings.get('account')}, open positions {len(positions)}")
    for position in positions:
        print(f"  {position.get('symbol')} {position.get('position')} "
              f"at {position.get('avgCost')}, worth {position.get('marketValue')}, "
              f"profit so far {position.get('unrealizedPnl')}")

    orders = (client.open_orders() or {}).get("orders", [])
    print(f"open orders: {len(orders)}")

    bars = client.bars_5m_today({"symbol": "SPY", "secType": "STK",
                                 "exchange": "SMART", "currency": "USD"})
    vwap = session_vwap(bars)
    print(f"SPY five minute bars today: {len(bars)}, "
          f"last close {bars[-1]['close'] if bars else None}, "
          f"session vwap {round(vwap, 2) if vwap else None}")
    print("OK, read only, nothing was ordered")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
