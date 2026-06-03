"""HTTP API for the bridge (V2 #3).

Ships as a separate process from the WebSocket bridge: the bridge
writes to sqlite on every state change, the API reads from sqlite.
This is the "C" integration option from the V2 #3 plan (cross-process
state via sqlite is the cleanest way to share without inventing RPC).

Why two processes (not one):
  - Keeps the websocket hot-path (8000) small and not coupled to uvicorn.
  - Lets the API be restarted / scaled independently.
  - No port collision; nginx proxies /api/ to the API on 8001 and
    /xiaozhi/ to the bridge on 8000.

V1 caveat: the bridge does NOT yet call db.upsert_*() in its hot path.
The API returns empty results until bridge integration lands (V2 #3
Step 5). This module ships working schemas + endpoints so the web
admin console can be wired up incrementally.
"""

from .db import BridgeDB, get_db
from .main import app, create_app

__all__ = ["BridgeDB", "get_db", "app", "create_app"]
