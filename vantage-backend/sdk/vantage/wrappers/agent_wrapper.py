"""
vantage/wrappers/agent_wrapper.py
=====================================
Wraps AI coding agents (GitHub Copilot, Windsurf, Cursor, Claude Code)
at the HTTP proxy level. These agents make OpenAI-compatible API calls
internally — we intercept them transparently.

HOW IT WORKS:
  These agents all talk to either:
    - api.openai.com   (Copilot, Cursor)
    - api.anthropic.com (Claude Code, Windsurf)
    - A custom endpoint

  We run a local proxy on 127.0.0.1:PORT that forwards to the real endpoint,
  captures every request/response, and sends stats to Vantage.

USAGE:
  import vantage
  from vantage.wrappers.agent_wrapper import AgentProxy

  vantage.init(api_key="crt_...", agent="copilot", team="engineering")

  # Start the local proxy
  proxy = AgentProxy(
      target_host = "https://api.openai.com",
      local_port  = 8877,
      agent_name  = "copilot",
  )
  proxy.start()
  # Set HTTP_PROXY=http://127.0.0.1:8877 in your agent's environment
  # The agent now routes through Vantage transparently

ENVIRONMENT SETUP:
  export OPENAI_API_BASE=http://127.0.0.1:8877  # for Copilot
  export ANTHROPIC_BASE_URL=http://127.0.0.1:8878  # for Claude Code
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

logger = logging.getLogger("vantage.agent")

# Known agents and their default target URLs
AGENT_TARGETS = {
    "copilot":     "https://api.githubcopilot.com",
    "cursor":      "https://api.openai.com",
    "windsurf":    "https://api.anthropic.com",
    "claude-code": "https://api.anthropic.com",
    "codeium":     "https://api.codeium.com",
    "custom":      "https://api.openai.com",   # override via target_host
}

# Map agent → provider name
AGENT_PROVIDER = {
    "copilot":     "openai",
    "cursor":      "openai",
    "windsurf":    "anthropic",
    "claude-code": "anthropic",
    "codeium":     "codeium",
    "custom":      "openai",
}


class AgentProxy:
    """
    Local HTTP proxy that intercepts AI agent API calls.
    Forwards to the real AI provider while capturing all statistics.
    """

    def __init__(
        self,
        target_host: str = "https://api.openai.com",
        local_port:  int  = 8877,
        agent_name:  str  = "custom",
    ):
        self.target_host = target_host.rstrip("/")
        self.local_port  = local_port
        self.agent_name  = agent_name
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start proxy in background thread."""
        proxy = self   # capture for handler class

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass  # suppress default logs

            def do_POST(self): proxy._handle(self, "POST")
            def do_GET(self):  proxy._handle(self, "GET")

        self._server = HTTPServer(("127.0.0.1", self.local_port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="vantage-proxy"
        )
        self._thread.start()
        logger.info(
            "[vantage] AgentProxy started — 127.0.0.1:%d → %s",
            self.local_port, self.target_host
        )

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    def _handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        t_start = time.perf_counter()

        # Read request body
        length   = int(handler.headers.get("Content-Length", 0))
        req_body = handler.rfile.read(length) if length > 0 else b""

        # Forward to real endpoint
        target_url = self.target_host + handler.path
        forward_headers = {
            k: v for k, v in handler.headers.items()
            if k.lower() not in ("host", "content-length")
        }

        try:
            req = urllib.request.Request(
                target_url,
                data=req_body if req_body else None,
                headers=forward_headers,
                method=method,
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_body   = resp.read()
                status_code = resp.status
                resp_headers = dict(resp.headers)
        except urllib.error.HTTPError as e:
            resp_body   = e.read()
            status_code = e.code
            resp_headers = {}
        except Exception as e:
            logger.error("[vantage] Proxy forward error: %s", e)
            handler.send_response(502)
            handler.end_headers()
            return

        latency_ms = (time.perf_counter() - t_start) * 1000

        # Send response back to agent
        handler.send_response(status_code)
        for k, v in resp_headers.items():
            if k.lower() not in ("transfer-encoding", "content-encoding"):
                handler.send_header(k, v)
        handler.send_header("Content-Length", str(len(resp_body)))
        handler.end_headers()
        handler.wfile.write(resp_body)

        # Parse and capture metrics (non-blocking)
        threading.Thread(
            target=self._capture,
            args=(req_body, resp_body, handler.path, latency_ms, status_code),
            daemon=True,
        ).start()

    def _capture(
        self,
        req_body:    bytes,
        resp_body:   bytes,
        path:        str,
        latency_ms:  float,
        status_code: int,
    ) -> None:
        """Parse the request/response bodies and capture a CohrintEvent."""
        try:
            import vantage as sdk
            client = sdk.get_client()
        except RuntimeError:
            return  # Vantage not initialised

        try:
            req_data  = json.loads(req_body)  if req_body  else {}
            resp_data = json.loads(resp_body) if resp_body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        # Extract from OpenAI-compatible format
        model    = req_data.get("model", "unknown")
        messages = req_data.get("messages", [])
        provider = AGENT_PROVIDER.get(self.agent_name, "openai")

        # Parse usage from response
        usage          = resp_data.get("usage", {})
        prompt_tokens  = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
        comp_tokens    = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
        cached_tokens  = (
            usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            or usage.get("cache_read_input_tokens", 0)
        )

        # Calculate cost
        from vantage.models.pricing import calculate_cost, find_cheapest_alternative
        _, _, total_cost = calculate_cost(model, prompt_tokens, comp_tokens, cached_tokens)
        alt = find_cheapest_alternative(model, prompt_tokens, comp_tokens)

        # Extract request/response previews
        user_msgs   = [m for m in messages if m.get("role") == "user"]
        sys_msgs    = [m for m in messages if m.get("role") == "system"]
        req_preview = str(user_msgs[-1].get("content", "") if user_msgs else "")[:500]
        sys_preview = str(sys_msgs[0].get("content", "")  if sys_msgs  else "")[:200]

        # Extract response content
        choices = resp_data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {}) or choices[0].get("delta", {})
            resp_preview = str(msg.get("content", ""))[:500]
        elif "content" in resp_data:  # Anthropic format
            content = resp_data["content"]
            resp_preview = str(content[0].get("text", "") if content else "")[:500]
        else:
            resp_preview = ""

        # System prompt tokens estimate
        sys_token_estimate = sum(len(m.get("content","")) // 4 for m in sys_msgs)

        from vantage.models.event import CohrintEvent
        event = CohrintEvent(
            provider              = provider,
            model                 = model,
            agent                 = self.agent_name,
            endpoint              = path,
            latency_ms            = latency_ms,
            status_code           = status_code,
            prompt_tokens         = prompt_tokens,
            completion_tokens     = comp_tokens,
            total_tokens          = prompt_tokens + comp_tokens,
            cached_tokens         = cached_tokens,
            system_prompt_tokens  = sys_token_estimate,
            total_cost_usd        = total_cost,
            cheapest_model        = alt.name if alt else "",
            potential_saving_usd  = max(0.0, total_cost - alt.cost) if alt else 0.0,
            request_preview       = req_preview,
            response_preview      = resp_preview,
            system_preview        = sys_preview,
        )
        client.capture(event)


def wrap_agent(agent: str, port: int = 8877) -> AgentProxy:
    """
    Convenience function — start a proxy for a named agent.

    Usage:
        proxy = vantage.wrappers.wrap_agent("copilot", port=8877)
        # Then: export OPENAI_API_BASE=http://127.0.0.1:8877
    """
    target = AGENT_TARGETS.get(agent, "https://api.openai.com")
    proxy  = AgentProxy(target_host=target, local_port=port, agent_name=agent)
    proxy.start()
    return proxy
