from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import os
import uuid
import asyncio
import time
import io
from urllib.parse import quote

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


def _service_log(message: str):
    print(f"[DXF工具] {message}", flush=True)


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
    _service_log(
        f"上传DXF：session={session_id[:8]}，文件={file.filename}，实体数={len(list(working_doc.modelspace()))}"
    )

    return {
        "session_id": session_id,
        "base_svg": base.svg_string,
        "hover_paths": _hover_path_payload(state),
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
    axis = geometry_utils.estimate_chain_symmetry_axis(state.working_doc, chain)
    apex = geometry_utils.top_axis_sample_on_chain(state.working_doc, chain, axis)
    state.manual_apex_distance = apex.distance if apex is not None else None
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


def _hover_path_payload(state: SessionState) -> list[dict]:
    """Return lightweight front-end hit paths for selectable base entities."""
    paths = []
    for entity in state.working_doc.modelspace():
        if entity.dxftype() not in entity_mapper.EDGE_TYPES:
            continue
        handle = entity.dxf.handle
        path_d = entity_mapper.entity_to_svg_path(state, handle)
        if path_d:
            paths.append({"handle": handle, "path_d": path_d})
    return paths


@app.post("/api/session/{session_id}/select")
async def select_entity(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    append = bool(data.get("append", False))
    handle = _select_handle(state, data)
    if not handle:
        _service_log(f"选择边失败：session={session_id[:8]}，附近没有可选对象")
        return {"status": "no_selection"}

    _apply_selection(state, handle, append)
    regenerate(state)
    _service_log(
        f"选择可选边：session={session_id[:8]}，handle={handle}，追加={append}，"
        f"已选边={len(state.selected_handles)}，链段={state.chain_info.get('segment_count', 0)}"
    )

    return _preview_payload(state)["data"]


@app.post("/api/session/{session_id}/params")
async def update_params(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    state.params = CircleParams.from_dict(data)
    regenerate(state)
    _service_log(
        f"更新参数：session={session_id[:8]}，射线数量={state.params.ray_count}，"
        f"圆半径={state.params.circle_radius}，每射线圆数={state.params.circles_per_ray}，"
        f"顶部间隔={state.params.top_gap_distance}，长条起点距离={state.params.capsule_start_distance}，"
        f"胶囊安全间距={state.params.capsule_clearance_distance}"
    )

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
    _service_log(f"切换预览显示：session={session_id[:8]}，显示生成图={state.show_generated}")
    return {"show_generated": state.show_generated}


@app.get("/api/session/{session_id}/download")
async def download_dxf(session_id: str):
    """The ONLY place where the DXF is mutated: clone original, add circles, stream."""
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
            _service_log(f"生成DXF失败：session={session_id[:8]}，错误={e}")
        else:
            _service_log(
                f"导出DXF：session={session_id[:8]}，链段={len(state.selected_chain)}，"
                f"生成数量={state.preview_geometry.get('generated_count', 0)}"
            )
    else:
        _service_log(f"导出DXF：session={session_id[:8]}，没有选中边，仅导出原图")

    stream = io.StringIO()
    output_doc.write(stream)
    filename = f"generated_{session_id[:8]}.dxf"
    return Response(
        content=stream.getvalue().encode("utf-8", errors="replace"),
        media_type="application/dxf",
        headers={
            "Content-Disposition": (
                f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store, max-age=0",
        },
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


def _preview_payload(state: SessionState, **extra_data):
    data = {
        "preview_geometry": state.preview_geometry,
        "selected_handles": state.selected_handles,
        "selected_chain": state.selected_chain,
        "chain_info": state.chain_info,
        "show_generated": state.show_generated,
        "manual_apex_distance": state.manual_apex_distance,
        "generated_count": state.preview_geometry.get("generated_count", 0),
    }
    data.update(extra_data)
    return {
        "type": "preview_update",
        "data": data,
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
                    _service_log(f"选择边失败：session={session_id[:8]}，附近没有可选对象")
                    await websocket.send_json({"type": "no_selection", "data": {}})
                    continue

                _apply_selection(state, handle, append)
                regenerate(state)
                _service_log(
                    f"选择可选边：session={session_id[:8]}，handle={handle}，追加={append}，"
                    f"已选边={len(state.selected_handles)}，链段={state.chain_info.get('segment_count', 0)}"
                )
                await websocket.send_json(_preview_payload(state))

            elif msg_type == "params_change":
                seq = data.get("seq", None)
                state.params = CircleParams.from_dict(data.get("params", {}))
                regenerate(state)
                _service_log(
                    f"更新参数：session={session_id[:8]}，seq={seq}，射线数量={state.params.ray_count}，"
                    f"圆半径={state.params.circle_radius}，每射线圆数={state.params.circles_per_ray}，"
                    f"顶部间隔={state.params.top_gap_distance}，长条起点距离={state.params.capsule_start_distance}，"
                    f"胶囊安全间距={state.params.capsule_clearance_distance}"
                )
                extra = {"params_seq": seq} if seq is not None else {}
                await websocket.send_json(_preview_payload(state, **extra))


            elif msg_type == "toggle_preview":
                state.show_generated = bool(data.get("show_generated", True))
                _service_log(f"切换预览显示：session={session_id[:8]}，显示生成图={state.show_generated}")
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
                _service_log(f"清空选择：session={session_id[:8]}")
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
