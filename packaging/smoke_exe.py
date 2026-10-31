"""Exercise the packaged Windows GUI and service without a Python installation on PATH."""
import argparse
import asyncio
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import ezdxf
from shapely.geometry import Point, Polygon
import websockets

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def request(base, path, data=None, headers=None):
    headers = dict(headers or {})
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    return urllib.request.urlopen(
        urllib.request.Request(base + path, data=data, headers=headers), timeout=30,
    )


def upload(base, doc):
    stream = io.StringIO()
    doc.write(stream)
    boundary = uuid.uuid4().hex
    data = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="smoke.dxf"\r\n'
        'Content-Type: application/dxf\r\n\r\n'
    ).encode() + stream.getvalue().encode() + f'\r\n--{boundary}--\r\n'.encode()
    with request(base, "/api/upload", data, {"Content-Type": f"multipart/form-data; boundary={boundary}"}) as response:
        return json.load(response)


async def select(base, sid, handle):
    async with websockets.connect(base.replace("http://", "ws://") + "/ws/" + sid) as ws:
        await ws.send(json.dumps({"type": "svg_click", "data": {"handle": handle, "append": False}}))
        response = json.loads(await ws.recv())
        assert response["type"] == "preview_update", response
        return response["data"]["preview_geometry"]


def check_case(base, doc, handle, params, expected_repairs, curved=False):
    result = upload(base, doc)
    assert result["base_svg"] and result["hover_paths"]
    sid = result["session_id"]
    settings = dict(result["params"], **params)
    with request(base, "/api/session/" + sid + "/params", settings) as response:
        assert json.load(response)["params"] == settings
    geometry = asyncio.run(select(base, sid, handle))
    assert geometry["safety"]["status"] == "ready", geometry["safety"]
    assert not geometry["safety"]["blocked"]
    assert geometry["safety"]["repaired_edge_count"] == expected_repairs
    assert geometry["generated_count"] > 0
    if curved:
        inner = [d for d in geometry["air_ducts"] if d["region"].endswith("_inner")]
        assert {d["region"] for d in inner} == {"upper_inner", "lower_inner"}
        assert all(d["d"].count("L ") > 12 for d in inner)

    previous_ducts = None
    for _ in range(2):
        with request(base, "/api/session/" + sid + "/download") as response:
            exported = ezdxf.read(io.StringIO(response.read().decode("utf-8")))
        holes = list(exported.modelspace().query('CIRCLE[layer=="GENERATED_CIRCLES"]'))
        assert len(holes) == geometry["generated_count"]
        repairs = list(exported.modelspace().query('LINE[layer=="AUTO_CLOSED_OUTLINE"]'))
        assert len(repairs) == expected_repairs
        ducts = list(exported.modelspace().query('LWPOLYLINE[layer=="GENERATED_AIR_DUCTS"]'))
        assert len(ducts) == geometry["air_duct_count"]
        assert all(d.closed and Polygon([(v[0], v[1]) for v in d.get_points()]).is_valid for d in ducts)
        coordinates = [list(d.get_points()) for d in ducts]
        if previous_ducts is not None:
            assert coordinates == previous_ducts, "repeated exports changed duct geometry"
        previous_ducts = coordinates
        if expected_repairs:
            boundary = Polygon([(0, 0), (200, 0), (200, 100), (0, 100)])
            assert all(boundary.boundary.distance(Point(e.dxf.center.x, e.dxf.center.y)) >= e.dxf.radius for e in holes)
    return {"holes": geometry["generated_count"], "ducts": geometry["air_duct_count"], "repairs": expected_repairs}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--service-only", action="store_true")
    args = parser.parse_args()
    executable = args.exe.resolve(strict=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="dxf-exe-smoke-") as directory:
        runtime = Path(directory)
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(key, None)
        env.update({
            "PATH": str(Path(os.environ["SystemRoot"]) / "System32") + ";" + os.environ["SystemRoot"],
            "LOCALAPPDATA": str(runtime / "data"),
            "XDG_CONFIG_HOME": str(runtime / "config"),
            "XDG_CACHE_HOME": str(runtime / "cache"),
            "PYTHONUTF8": "1",
        })
        command = [str(executable), "--port", str(port)]
        if args.service_only:
            command += ["--service-child", "--host", "127.0.0.1"]
        with (runtime / "process.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 90
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"EXE exited with {process.returncode}")
                    try:
                        with request(base, "/openapi.json") as response:
                            assert json.load(response)["info"]["version"] == args.version
                        break
                    except (OSError, urllib.error.URLError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Packaged app did not start within 90 seconds")
                        time.sleep(0.5)
                for path in ("/", "/static/js/i18n.js", "/static/js/app.js", "/static/assets/app-icon.ico"):
                    with request(base, path) as response:
                        assert response.status == 200 and response.read()

                doc = ezdxf.new()
                ellipse = doc.modelspace().add_ellipse((0, 0), major_axis=(0, 400), ratio=0.3)
                curved = check_case(base, doc, ellipse.dxf.handle, {
                    "circle_radius": 2, "ray_offset": 20, "circle_spacing": 10,
                    "circles_per_ray": 3, "ray_count": 120, "top_gap_distance": 0,
                    "air_duct_inlet_distance": 20, "capsule_axis_gap_above_distance": 150,
                    "capsule_axis_gap_below_distance": 150,
                }, 0, curved=True)
                doc = ezdxf.new()
                edge = doc.modelspace().add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)])
                repaired = check_case(base, doc, edge.dxf.handle, {
                    "circle_radius": 2, "ray_offset": 10, "circles_per_ray": 1,
                    "ray_count": 24, "top_gap_distance": 0, "air_duct_enabled": False,
                }, 1)
                print(json.dumps({"exe": executable.name, "version": args.version,
                                  "gui": not args.service_only, "curved_board": curved,
                                  "open_board": repaired, "repeat_export": "passed"}))
            finally:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                process.wait(timeout=15)
                diagnostic_dir = Path(__file__).resolve().parents[1] / "build" / "smoke-logs"
                diagnostic_dir.mkdir(parents=True, exist_ok=True)
                for path in runtime.rglob("*.log"):
                    content = path.read_text(encoding="utf-8", errors="replace")
                    (diagnostic_dir / path.name).write_text(content, encoding="utf-8")
                    print(f"--- {path.name} ---\n{content}")


if __name__ == "__main__":
    main()
