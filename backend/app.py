from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from ezdxf.math import Vec2
import os
import uuid
import asyncio
import time

from backend.config import BASE_DIR, TEMP_DIR, GENERATED_LAYER
from backend.state import (
    SessionState,
    CircleParams,
    get_session,
    create_session,
    delete_session,
    delete_other_sessions,
    prune_sessions,
)
from backend.dxf_engine import loader, svg_exporter, entity_mapper, path_analyzer, circle_generator, geometry_utils

app = FastAPI(title="DXF 自动图形工具")
SESSION_TTL_SECONDS = 60 * 60
TEMP_FILE_TTL_SECONDS = 24 * 60 * 60

frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


def _cleanup_temp_files(active_session_id: Optional[str] = None):
    now = time.time()
    active_prefix = f"{active_session_id}" if active_session_id else None
    for path in TEMP_DIR.glob("*.dxf"):
        if active_prefix and path.name.startswith(active_prefix):
            continue
        try:
            if now - path.stat().st_mtime > TEMP_FILE_TTL_SECONDS:
                path.unlink()
        except OSError:
            pass


def _remove_session_files(session_ids: list[str]):
    for session_id in session_ids:
        for suffix in [".dxf", "_download.dxf"]:
            try:
                os.remove(TEMP_DIR / f"{session_id}{suffix}")
            except FileNotFoundError:
                pass


@app.get("/")
async def root():
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(
            str(index_file),
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    return {"message": "DXF 自动图形工具后端已启动"}


@app.post("/api/upload")
async def upload_dxf(file: UploadFile = File(...)):
    _remove_session_files(prune_sessions(SESSION_TTL_SECONDS))
    _cleanup_temp_files()

    if not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="请上传 .dxf 文件")

    session_id = str(uuid.uuid4())
    temp_path = TEMP_DIR / f"{session_id}.dxf"

    content = await file.read()
    with open(temp_path, "wb") as f:
        f.write(content)

    try:
        doc = loader.load_dxf(str(temp_path))
        if GENERATED_LAYER not in doc.layers:
            doc.layers.add(GENERATED_LAYER)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析 DXF: {e}")

    original_doc = loader.copy_dxf(doc)
    working_doc = loader.copy_dxf(doc)

    # Accurate base SVG rendered once (handles blocks, OCS, text, ...).
    base = svg_exporter.doc_to_base_svg(original_doc, dark=True)

    state = SessionState(
        session_id=session_id,
        original_doc=original_doc,
        working_doc=working_doc,
        base_svg_string=base.svg_string,
        svg_bounds=base.bounds,
        svg_scale=base.scale,
        original_bounds=base.bounds,
        chain_info={"total_length": 0.0, "segment_count": 0, "is_closed": False},
    )
    create_session(session_id, state)
    _remove_session_files(delete_other_sessions(session_id))
    _cleanup_temp_files(active_session_id=session_id)

    return {
        "session_id": session_id,
        "base_svg": base.svg_string,
        "bounds": base.bounds,
        "scale": base.scale,
        "entity_count": len(list(working_doc.modelspace())),
        "params": state.params.to_dict(),
        "show_generated": state.show_generated,
    }


@app.get("/api/session/{session_id}/svg")
async def get_svg(session_id: str):
    """Return the cached accurate base SVG (original drawing only)."""
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")
    return Response(content=state.base_svg_string, media_type="image/svg+xml")


def _select_handle(state: SessionState, data: dict) -> Optional[str]:
    """Find the entity handle nearest to a click given in base-SVG output units."""
    svg_x = float(data.get("svg_x", 0))
    svg_y = float(data.get("svg_y", 0))
    tol = data.get("tol", None)
    try:
        tol = float(tol) if tol is not None else None
    except (TypeError, ValueError):
        tol = None
    return entity_mapper.find_nearest_entity(state, svg_x, svg_y, tol=tol)


def _apply_selection(state: SessionState, handle: Optional[str], append: bool) -> bool:
    """Update selection state from a handle. Returns True if selection changed."""
    if not handle:
        return False

    if not append:
        state.selected_handles = []

    if handle in state.selected_handles:
        return False

    state.selected_handles.append(handle)
    chain = path_analyzer.build_chain(state.working_doc, state.selected_handles)
    state.selected_chain = chain
    state.chain_info = path_analyzer.get_chain_info(state.working_doc, chain)
    state.manual_apex_distance = None
    return True


def _set_manual_apex(state: SessionState, data: dict) -> bool:
    if not state.selected_chain:
        return False
    svg_x = float(data.get("svg_x", 0))
    svg_y = float(data.get("svg_y", 0))
    wcs_x, wcs_y = svg_exporter.svg_to_wcs(
        svg_x, svg_y, state.svg_bounds, state.svg_scale
    )
    sample = geometry_utils.nearest_sample_on_chain(
        state.working_doc,
        state.selected_chain,
        Vec2(wcs_x, wcs_y),
    )
    if sample is None:
        return False
    state.manual_apex_distance = sample.distance
    return True


def regenerate(state: SessionState):
    """Recompute the lightweight overlay geometry (no DXF mutation)."""
    closed = state.chain_info.get("is_closed", False)
    state.preview_geometry = circle_generator.compute_preview_geometry(
        state.working_doc,
        state.selected_chain,
        state.params,
        closed=closed,
        bounds=state.svg_bounds,
        scale=state.svg_scale,
        manual_apex_distance=state.manual_apex_distance,
    )


@app.post("/api/session/{session_id}/select")
async def select_entity(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    append = bool(data.get("append", False))
    handle = _select_handle(state, data)
    if not handle:
        raise HTTPException(status_code=404, detail="未找到 nearby 实体")

    _apply_selection(state, handle, append)
    regenerate(state)

    return _preview_payload(state)["data"]


@app.post("/api/session/{session_id}/params")
async def update_params(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    state.params = CircleParams.from_dict(data)
    regenerate(state)

    return {
        "params": state.params.to_dict(),
        "chain_info": state.chain_info,
        "preview_geometry": state.preview_geometry,
    }


@app.post("/api/session/{session_id}/toggle-preview")
async def toggle_preview(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    state.show_generated = bool(data.get("show_generated", True))
    return {"show_generated": state.show_generated}


@app.get("/api/session/{session_id}/download")
async def download_dxf(session_id: str):
    """The ONLY place where the DXF is mutated: clone original, add circles, save."""
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    output_doc = loader.copy_dxf(state.original_doc)
    if GENERATED_LAYER not in output_doc.layers:
        output_doc.layers.add(GENERATED_LAYER)

    if state.selected_chain:
        try:
            circle_generator.generate_circles(
                output_doc,
                state.selected_chain,
                state.params,
                closed=state.chain_info.get("is_closed", False),
                manual_apex_distance=state.manual_apex_distance,
            )
        except Exception as e:
            print(f"生成圆失败: {e}")

    temp_path = TEMP_DIR / f"{session_id}_download.dxf"
    loader.save_dxf(output_doc, str(temp_path))

    return FileResponse(
        str(temp_path),
        filename=f"generated_{session_id[:8]}.dxf",
        media_type="application/dxf",
    )


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    delete_session(session_id)
    for suffix in [".dxf", "_download.dxf"]:
        try:
            os.remove(TEMP_DIR / f"{session_id}{suffix}")
        except FileNotFoundError:
            pass
    return {"success": True}


def _preview_payload(state: SessionState):
    return {
        "type": "preview_update",
        "data": {
            "preview_geometry": state.preview_geometry,
            "selected_handles": state.selected_handles,
            "selected_chain": state.selected_chain,
            "chain_info": state.chain_info,
            "show_generated": state.show_generated,
            "manual_apex_distance": state.manual_apex_distance,
            "generated_count": state.preview_geometry.get("generated_count", 0),
        },
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    state = get_session(session_id)
    if not state:
        await websocket.send_json({"type": "error", "data": {"message": "会话不存在"}})
        await websocket.close()
        return

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            data = message.get("data", {})

            if msg_type == "svg_click":
                append = bool(data.get("append", False))
                handle = _select_handle(state, data)
                if not handle:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "未找到 nearby 实体"},
                    })
                    continue

                _apply_selection(state, handle, append)
                regenerate(state)
                await websocket.send_json(_preview_payload(state))

            elif msg_type == "params_change":
                state.params = CircleParams.from_dict(data.get("params", {}))
                regenerate(state)
                await websocket.send_json(_preview_payload(state))

            elif msg_type == "set_apex":
                if not _set_manual_apex(state, data):
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "请先选中一条边线，再在线上选择顶点"},
                    })
                    continue
                regenerate(state)
                await websocket.send_json(_preview_payload(state))

            elif msg_type == "toggle_preview":
                state.show_generated = bool(data.get("show_generated", True))
                await websocket.send_json(_preview_payload(state))

            elif msg_type == "svg_hover":
                request_id = data.get("request_id", None)
                handle = _select_handle(state, data)
                if handle:
                    path_d = entity_mapper.entity_to_svg_path(state, handle)
                    await websocket.send_json({
                        "type": "hover_result",
                        "data": {
                            "handle": handle,
                            "path_d": path_d,
                            "request_id": request_id,
                        },
                    })
                else:
                    await websocket.send_json({
                        "type": "hover_clear",
                        "data": {"request_id": request_id},
                    })

            elif msg_type == "clear_selection":
                state.selected_handles = []
                state.selected_chain = []
                state.manual_apex_distance = None
                state.chain_info = {
                    "total_length": 0.0,
                    "segment_count": 0,
                    "is_closed": False,
                }
                regenerate(state)
                await websocket.send_json({"type": "cleared", "data": {}})

            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"未知消息类型: {msg_type}"},
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "data": {"message": str(e)}})
        await websocket.close()
