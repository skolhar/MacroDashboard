"""Tapetide index-history adapter: exchange-official daily EOD bars via MCP.

Tapetide's documented MCP server (mcp.tapetide.com/mcp, bearer token, free
tier) serves daily OHLC for NSE indices, labelled exchange-official, including
the latest completed session before Yahoo publishes it. Failures fail closed;
no synthetic fallback.
"""
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from .base import Instrument, MarketBatch, MarketCandle
from .yahoo import MarketSourceUnavailable

MCP_URL = "https://mcp.tapetide.com/mcp"
SOURCE_URL = "https://tapetide.com/insight/market-valuation"


def _mcp_tool(tool: str, arguments: dict) -> dict:
    token = os.environ.get("TAPETIDE_API_TOKEN", "").strip()
    if not token:
        raise MarketSourceUnavailable("TapetideTokenNotConfigured")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    with httpx.Client(timeout=httpx.Timeout(60, connect=5)) as client:
        r = client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "smarthedge", "version": "1.0"}}}, headers=headers)
        r.raise_for_status()
        session_id = r.headers.get("mcp-session-id")
        headers["Mcp-Session-Id"] = session_id
        client.post(MCP_URL, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
        r = client.post(MCP_URL, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": tool, "arguments": arguments}}, headers=headers)
        r.raise_for_status()
        body = r.text
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            for line in body.splitlines():
                if line.startswith("data:"):
                    body = line[5:].strip()
                    break
        response = json.JSONDecoder().raw_decode(body)[0]
        if response.get("error"):
            raise MarketSourceUnavailable(f"TapetideMcpError:{response['error'].get('code', 'unknown')}")
        result = response.get("result", {})
        if result.get("isError"):
            raise MarketSourceUnavailable("TapetideToolError")
        content = result.get("content", [])
        text = content[0].get("text", "") if content else ""
        payload, _ = json.JSONDecoder().raw_decode(text)
        return payload


class TapetideProvider:
    name = "tapetide"

    def fetch_daily(self, instrument: Instrument, start: date, end: date) -> MarketBatch:
        symbol = instrument.symbol(self.name)
        if not symbol or start >= end or (end - start).days > 366:
            raise ValueError("Tapetide symbol or requested history range is invalid")
        span = (end - start).days
        interval = "1m" if span <= 31 else "3m" if span <= 93 else "6m" if span <= 186 else "1y"
        payload = _mcp_tool("get_index_history", {"index_name": symbol, "interval": interval})
        meta = payload.get("meta", {})
        if meta.get("truncated"):
            raise MarketSourceUnavailable("TapetideResponseTruncated")
        data = payload.get("data", {})
        bars = data.get("bars", [])
        if not bars:
            raise MarketSourceUnavailable("TapetideNoBars")
        candles = []
        for bar in bars:
            day = date.fromisoformat(bar["date"])
            if not start <= day < end:
                continue
            candles.append(MarketCandle(
                session_date=day,
                open=Decimal(str(bar["open"])), high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])), close=Decimal(str(bar["close"])),
                adjusted_close=None, volume=None,
            ))
        if not candles:
            raise MarketSourceUnavailable("TapetideNoBarsInRange")
        now = datetime.now(timezone.utc)
        return MarketBatch(
            instrument=instrument, provider=self.name, symbol=symbol,
            retrieved_at=now, source_url=SOURCE_URL,
            candles=tuple(candles), exchange_timezone=instrument.timezone,
            quality="secondary_unverified", eod_confirmed=True,
        )
