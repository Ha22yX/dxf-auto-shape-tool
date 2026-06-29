"""Test WebSocket click with handle."""
import asyncio
import json
import sys

import websockets


async def run_test(session_id: str):
    uri = f"ws://127.0.0.1:8000/ws/{session_id}"
    async with websockets.connect(uri) as ws:
        # Click with handle directly
        await ws.send(json.dumps({
            "type": "svg_click",
            "data": {"svg_x": 0, "svg_y": 0, "append": False, "handle": "2E0"},
        }))
        msg = json.loads(await ws.recv())
        print("Handle click response:", msg["type"], msg["data"].get("chain_info"))
        assert msg["type"] == "preview_update"

    print("Handle-based click test passed")


if __name__ == "__main__":
    sid = sys.argv[1]
    asyncio.run(run_test(sid))
