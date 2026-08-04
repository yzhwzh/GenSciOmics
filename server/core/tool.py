"""Unified Tool Interface — 对齐 Claude Code 的 Tool 接口 (src/Tool.ts + buildTool()).

所有工具（Native + MCP）统一用此 Tool dataclass。
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

# ── Global tool registry (flat list, like Claude Code's Tools array) ──────
# Thread safety: ALL_TOOLS is mutated at import time (single-threaded) and
# during MCP init (lazy, first request). After startup it's read-only.
# all_tools_lock protects concurrent mutations.
ALL_TOOLS: list[Tool] = []
_all_tools_lock = threading.Lock()


def add_tool(tool: Tool):
    """Thread-safe add/replace a tool in ALL_TOOLS."""
    with _all_tools_lock:
        for i, t in enumerate(ALL_TOOLS):
            if t.name == tool.name:
                ALL_TOOLS[i] = tool
                return
        ALL_TOOLS.append(tool)


def _default_schema() -> dict:
    return {'type': 'object', 'properties': {}, 'required': []}


@dataclass
class Tool:
    """统一 Tool 类型 — 对齐 Claude Code 的 Tool 接口。

    对应 src/Tool.ts:
      name, description, inputSchema, outputSchema, call,
      isDeferred, isMcp, shouldDefer, alwaysLoad, maxResultSizeChars
    """
    name: str
    description: str = ''
    input_schema: dict = field(default_factory=_default_schema)
    output_schema: dict | None = None
    fn: Callable[..., Any] | None = None  # 执行函数 (Native)
    is_deferred: bool = False             # 需要 tool_search 发现
    is_mcp: bool = False                  # 是否 MCP 工具
    server_name: str = ''                 # MCP 服务器名
    mcp_tool_name: str = ''              # MCP 工具原始名
    max_result_size_chars: int = 100_000  # 对齐 Claude Code 的 maxResultSizeChars

    def to_openai_tool(self) -> dict | None:
        """输出 OpenAI function calling schema。
        无 fn 且非 MCP → SKILL.md-only → 返回 None。
        """
        if not self.is_mcp and self.fn is None:
            return None
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': self.input_schema,
            },
        }

    def call(self, **kwargs) -> Any:
        """执行工具 — 支持 Native fn 和 MCP proxy 两种模式。"""
        if self.is_mcp:
            from .mcp_manager import get_mcp_manager
            mgr = get_mcp_manager()
            if mgr is None:
                raise RuntimeError(f'MCP manager not initialized for {self.name}')
            return mgr.call_tool(self.server_name, self.mcp_tool_name, kwargs)
        if self.fn is None:
            raise RuntimeError(f'Tool {self.name} has no registered function')
        return self.fn(**kwargs)


# ── Deferred tool detection (对齐 isDeferredTool()) ──────────────────────

def is_deferred_tool(tool: Tool) -> bool:
    """判断工具是否需要 tool_search 发现。
    对应 Claude Code 的 isDeferredTool()。
    """
    if tool.name == 'tool_search':
        return False
    return tool.is_deferred


# ── Factory (对齐 buildTool()) ──────────────────────────────────────────

def build_tool(name: str, **overrides) -> Tool:
    """工厂函数 — 对应 Claude Code 的 buildTool()。"""
    kwargs = {'name': name}
    kwargs.update(overrides)
    if kwargs.get('is_mcp'):
        srv = kwargs.get('server_name', '')
        mcp = kwargs.get('mcp_tool_name', '')
        if srv and mcp:
            kwargs['name'] = f'mcp__{srv}__{mcp}'
    return Tool(**kwargs)


# ── Decorator (对齐 @register_tool) ─────────────────────────────────────

def register_tool(name: str = '', description: str = '',
                   input_schema: dict | None = None,
                   is_deferred: bool = False, is_mcp: bool = False,
                   **kwargs):
    """注册工具装饰器 — 对标 Claude Code 的 Tool 注册。

    用法:
        @register_tool(name='shell', description='...', input_schema={...})
        def shell(command: str, timeout: int = 120) -> dict: ...
    """
    def decorator(func):
        tool = Tool(
            name=name or func.__name__,
            description=description or func.__doc__ or '',
            input_schema=input_schema or _default_schema(),
            fn=func,
            is_deferred=is_deferred,
            is_mcp=is_mcp,
            **{k: v for k, v in kwargs.items()
               if k in ('server_name', 'mcp_tool_name', 'max_result_size_chars')},
        )
        add_tool(tool)
        return func
    return decorator


# ── Backward-compat aliases ──────────────────────────────────────────────

class MCPToolProxy(Tool):
    """保留兼容别名 — 新代码直接用 Tool(is_mcp=True)。"""
    def __init__(self, name: str, description: str, input_schema: dict,
                 server_name: str, mcp_tool_name: str):
        fq = f'mcp__{server_name}__{mcp_tool_name}'
        super().__init__(name=fq, description=description, input_schema=input_schema,
                         is_mcp=True, server_name=server_name, mcp_tool_name=mcp_tool_name)

    @property
    def fq_name(self) -> str:
        return self.name
