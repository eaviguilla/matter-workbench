"""python -m mcp_server  (Claude Desktop launches this over stdio)"""
from app.store import Store

from .server import serve

serve(lambda: Store.open())
