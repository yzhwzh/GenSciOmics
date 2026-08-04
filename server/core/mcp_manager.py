"""MCP Manager — 对标 Claude Code 的 services/mcp/client.ts。

管理 MCP Server 连接（HTTP + stdio），自动发现 tools 并注册到 ALL_TOOLS。
MCP 协议: JSON-RPC 2.0 over stdio 或 HTTP。
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from .tool import MCPToolProxy


def _normalize_name(name: str) -> str:
    """Normalize server/tool names (same as Claude Code normalizeNameForMCP)."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)


class MCPServerConnection:
    """A single MCP server connection (stdio or HTTP)."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.server_type = config.get('type', 'stdio')
        self._process: subprocess.Popen | None = None
        self._tools: list[dict] | None = None
        self._next_id = 1

    # ── Connection management ────────────────────────────────────

    def connect(self) -> bool:
        """Start the MCP server process (stdio) or validate URL (HTTP)."""
        if self.server_type == 'http':
            url = self.config.get('url', '')
            if not url:
                print(f'[mcp] ERROR: {self.name}: HTTP server requires url', file=sys.stderr)
                return False
            return True

        command = self.config.get('command', '')
        args = self.config.get('args', [])
        if not command:
            print(f'[mcp] ERROR: {self.name}: stdio server requires command', file=sys.stderr)
            return False

        env = os.environ.copy()
        for k, v in self.config.get('env', {}).items():
            env[k] = v

        try:
            self._process = subprocess.Popen(
                [command] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
            )
            time.sleep(0.3)
            if self._process.poll() is not None:
                stderr_out = self._process.stderr.read() if self._process.stderr else ''
                print(f'[mcp] ERROR: {self.name} exited: {stderr_out[:200]}',
                      file=sys.stderr)
                return False
            return True
        except FileNotFoundError as e:
            print(f'[mcp] ERROR: {self.name}: command not found: {command} ({e})',
                  file=sys.stderr)
            return False
        except Exception as e:
            print(f'[mcp] ERROR: {self.name} failed: {e}', file=sys.stderr)
            return False

    def disconnect(self):
        """Stop the MCP server process."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None

    # ── JSON-RPC communication ───────────────────────────────────

    def _send_request(self, method: str, params: dict | None = None) -> dict | None:
        req_id = self._next_id
        self._next_id += 1
        payload = {'jsonrpc': '2.0', 'id': req_id, 'method': method}
        if params:
            payload['params'] = params

        if self.server_type == 'http':
            return self._send_http(payload)
        return self._send_stdio(payload)

    def _send_stdio(self, payload: dict) -> dict | None:
        if not self._process or not self._process.stdin:
            return None
        try:
            line = json.dumps(payload)
            self._process.stdin.write(line + '\n')
            self._process.stdin.flush()

            response_line = self._process.stdout.readline() if self._process.stdout else ''
            if not response_line:
                return None
            response = json.loads(response_line)

            if 'error' in response:
                msg = response['error'].get('message', str(response['error']))
                print(f'[mcp] RPC error from {self.name}: {msg}', file=sys.stderr)
                return None
            return response.get('result')
        except Exception as e:
            print(f'[mcp] stdio error from {self.name}: {e}', file=sys.stderr)
            return None

    def _send_http(self, payload: dict) -> dict | None:
        url = self.config.get('url', '')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'User-Agent': 'GenSci-MCP/1.0',
        }
        api_key = self.config.get('api_key', '')
        if api_key:
            headers['x-api-key'] = api_key

        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode('utf-8', errors='replace')
                content_type = resp.headers.get('Content-Type', '')

            # Streamable HTTP may return SSE format: event: message\ndata: {...}
            if 'text/event-stream' in content_type or body.startswith('event:'):
                json_str = self._parse_sse(body)
                if json_str is None:
                    return None
                response = json.loads(json_str)
            else:
                response = json.loads(body)

            if 'error' in response:
                msg = response['error'].get('message', str(response['error']))
                print(f'[mcp] HTTP error from {self.name}: {msg}', file=sys.stderr)
                return None
            return response.get('result')
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:200]
            print(f'[mcp] HTTP {e.code} from {self.name}: {body}', file=sys.stderr)
            return None
        except Exception as e:
            print(f'[mcp] HTTP error from {self.name}: {e}', file=sys.stderr)
            return None

    @staticmethod
    def _parse_sse(body: str) -> str | None:
        """Parse SSE (Server-Sent Events) format, extract JSON from data: lines."""
        for line in body.split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                json_str = line[6:]  # strip 'data: ' prefix
                try:
                    # Parse to validate, return the string
                    json.loads(json_str)
                    return json_str
                except json.JSONDecodeError:
                    continue
        return None

    # ── Tool operations ──────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        if self._tools is not None:
            return self._tools
        result = self._send_request('tools/list')
        if result is None:
            self._tools = []
            return []
        self._tools = result.get('tools', [])
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        result = self._send_request('tools/call', {
            'name': tool_name,
            'arguments': arguments,
        })
        if result is None:
            return None
        content = result.get('content', [])
        texts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get('text', '')
                if text:
                    texts.append(text)
            elif isinstance(block, str):
                texts.append(block)
        return '\n'.join(texts) if texts else str(content)

    def is_alive(self) -> bool:
        if self.server_type == 'http':
            return True
        if self._process:
            return self._process.poll() is None
        return False


class MCPManager:
    """MCP 管理器——管理所有 MCP Server 连接和工具发现。

    对标 Claude Code 的 services/mcp/client.ts。
    """

    def __init__(self, servers_config: dict[str, dict] | None = None):
        self.servers: dict[str, MCPServerConnection] = {}
        self._tool_map: dict[str, MCPToolProxy] = {}

        if servers_config:
            for name, config in servers_config.items():
                self.add_server(name, config)

    def add_server(self, name: str, config: dict) -> bool:
        conn = MCPServerConnection(name, config)
        if not conn.connect():
            return False
        self.servers[name] = conn
        return True

    def remove_server(self, name: str):
        conn = self.servers.pop(name, None)
        if conn:
            conn.disconnect()

    def stop_all(self):
        for name, conn in list(self.servers.items()):
            conn.disconnect()
        self.servers.clear()
        self._tool_map.clear()

    def discover_all(self) -> list[MCPToolProxy]:
        """Discover tools from all connected MCP servers."""
        proxies = []
        for name, conn in self.servers.items():
            if not conn.is_alive():
                print(f'[mcp] {name} is not alive, skipping', file=sys.stderr)
                continue
            tools = conn.list_tools()
            for t in tools:
                tool_name = t.get('name', '')
                description = t.get('description', '')
                input_schema = t.get('inputSchema', {
                    'type': 'object', 'properties': {}, 'required': [],
                })
                proxy = MCPToolProxy(
                    name=f'mcp__{_normalize_name(name)}__{_normalize_name(tool_name)}',
                    description=description,
                    input_schema=input_schema,
                    server_name=name,
                    mcp_tool_name=tool_name,
                )
                proxies.append(proxy)
                self._tool_map[proxy.fq_name] = proxy
        return proxies

    def get_proxy(self, fq_name: str) -> MCPToolProxy | None:
        return self._tool_map.get(fq_name)

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Any:
        conn = self.servers.get(server_name)
        if not conn:
            print(f'[mcp] server not found: {server_name}', file=sys.stderr)
            return None
        if not conn.is_alive():
            print(f'[mcp] server {server_name} not alive', file=sys.stderr)
            return None
        return conn.call_tool(tool_name, arguments)

    def get_status(self) -> list[dict]:
        status = []
        for name, conn in self.servers.items():
            tools = conn._tools or []
            status.append({
                'name': name,
                'type': conn.server_type,
                'alive': conn.is_alive(),
                'tools': len(tools),
            })
        return status


# ── Module-level singleton accessor ──────────────────────────────────────
_mcp_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager | None:
    """Get or initialize the MCP Manager singleton.

    对标 Claude Code 的 appState.mcp 访问模式。
    """
    global _mcp_manager
    if _mcp_manager is None:
        from config import MCP_SERVERS
        enabled_servers = {
            name: cfg for name, cfg in MCP_SERVERS.items()
            if cfg.get('enabled', False)
        }
        if enabled_servers:
            _mcp_manager = MCPManager(enabled_servers)
    return _mcp_manager
