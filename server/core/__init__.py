"""GenSci Core — 统一工具接口 + MCP 管理器。"""
from .tool import Tool, MCPToolProxy, ALL_TOOLS, build_tool, register_tool, is_deferred_tool, add_tool
from .mcp_manager import MCPManager, MCPServerConnection, get_mcp_manager

__all__ = ['Tool', 'MCPToolProxy', 'ALL_TOOLS', 'build_tool',
           'register_tool', 'is_deferred_tool', 'MCPManager', 'MCPServerConnection',
           'get_mcp_manager']
