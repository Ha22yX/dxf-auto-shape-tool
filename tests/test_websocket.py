"""Quick WebSocket test for the DXF tool (requires running server)."""
import asyncio
import json
import sys
import os

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run_test(session_id: str):
    uri = f"ws://127.0.0.1:8000/ws/{session_id}"
    async with websockets.connect(uri) as ws:
        # Simulate click near middle of bottom line
        await ws.send(json.dumps({"type": "svg_click", "data": {"svg_x": 50, "svg_y": 0, "append": False}}))
        msg = json.loads(await ws.recv())
        print("Click response:", msg["type"], msg["data"].get("chain_info"))
        assert msg["type"] == "svg_update"
        assert len(msg["data"]["selected_chain"]) >= 1

        # Change params
        await ws.send(json.dumps({
            "type": "params_change",
            "data": {"params": {"circle_radius": 2, "circles_per_ray": 3, "circle_spacing": 5,
                               "ray_offset": 2, "ray_count": 8, "ray_direction": "inward"}},
        }))
        msg = json.loads(await ws.recv())
        print("Params response:", msg["type"], msg["data"].get("generated_count"))
        assert msg["data"]["generated_count"] > 0

    print("WebSocket test passed")


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if not sid:
        # Try to read from latest upload response
        try:
            with open("temp/upload_response.json") as f:
                data = json.load(f)
                sid = data["session_id"]
        except Exception:
            print("Usage: python tests/test_websocket.py <session_id>")
            sys.exit(1)
    asyncio.run(run_test(sid))
