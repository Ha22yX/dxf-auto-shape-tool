from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import os
import uuid
import asyncio

from backend.config import BASE_DIR, TEMP_DIR, GENERATED_LAYER
from backend.state import (
    SessionState,
    CircleParams,
    get_session,
    create_session,
    delete_session,
)
from backend.dxf_engine import loader, svg_exporter, entity_mapper, path_analyzer, circle_generator

app = FastAPI(title="DXF 自动图形工具")

frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def root():
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "DXF 自动图形工具后端已启动"}


@app.post("/api/upload")
async def upload_dxf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="请上传 .dxf 文件")

    session_id = str(uuid.uuid4())
    temp_path = TEMP_DIR / f"{session_id}.dxf"

    content = await file.read()
    with open(temp_path, "wb") as f:
        f.write(content)

    try:
        doc = loader.load_dxf(str(temp_path))
        # ensure generated layer exists
        if GENERATED_LAYER not in doc.layers:
            doc.layers.add(GENERATED_LAYER)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析 DXF: {e}")

    original_doc = loader.copy_dxf(doc)
    working_doc = loader.copy_dxf(doc)

    original_bounds = svg_exporter.compute_bounds(original_doc)
    svg_result = svg_exporter.doc_to_svg(working_doc, bounds=original_bounds)

    state = SessionState(
        session_id=session_id,
        original_doc=original_doc,
        working_doc=working_doc,
        svg_string_generated=svg_result.svg_string,
        svg_string_original=svg_result.svg_string,
        entity_svg_transform=svg_result.transform,
        original_bounds=original_bounds,
        chain_info={"total_length": 0.0, "segment_count": 0, "is_closed": False},
    )
    create_session(session_id, state)

    return {
        "session_id": session_id,
        "svg_url": f"/api/session/{session_id}/svg?generated=true",
        "bounds": svg_result.bounds,
        "entity_count": len(list(working_doc.modelspace())),
    }


@app.get("/api/session/{session_id}/svg")
async def get_svg(session_id: str, generated: bool = True):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    svg = state.svg_string_generated if generated else state.svg_string_original
    return Response(content=svg, media_type="image/svg+xml")


def _select_handle(state: SessionState, data: dict) -> Optional[str]:
    """Determine selected handle from frontend data."""
    if "handle" in data and data["handle"]:
        handle = data["handle"]
        entity = state.working_doc.entitydb.get(handle)
        if entity and entity.dxf.layer != GENERATED_LAYER:
            return handle
    # Fallback to coordinate search
    svg_x = float(data.get("svg_x", 0))
    svg_y = float(data.get("svg_y", 0))
    return entity_mapper.find_nearest_entity(state, svg_x, svg_y)


@app.post("/api/session/{session_id}/select")
async def select_entity(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    append = bool(data.get("append", False))
    handle = _select_handle(state, data)
    if not handle:
        raise HTTPException(status_code=404, detail="未找到 nearby 实体")

    if not append:
        state.selected_handles = []

    if handle not in state.selected_handles:
        state.selected_handles.append(handle)

    chain = path_analyzer.build_chain(state.working_doc, state.selected_handles)
    state.selected_chain = chain
    state.chain_info = path_analyzer.get_chain_info(state.working_doc, chain)

    # regenerate preview with current params
    regenerate(state)

    return {
        "selected_handles": state.selected_handles,
        "selected_chain": state.selected_chain,
        "chain_info": state.chain_info,
    }


@app.post("/api/session/{session_id}/params")
async def update_params(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    state.params = CircleParams.from_dict(data)
    regenerate(state)

    return {"params": state.params.to_dict(), "chain_info": state.chain_info}


@app.post("/api/session/{session_id}/toggle-preview")
async def toggle_preview(session_id: str, data: dict):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    state.show_generated = bool(data.get("show_generated", True))
    return {"show_generated": state.show_generated}


@app.get("/api/session/{session_id}/download")
async def download_dxf(session_id: str):
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在")

    temp_path = TEMP_DIR / f"{session_id}_download.dxf"
    loader.save_dxf(state.working_doc, str(temp_path))

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


def regenerate(state: SessionState):
    # start from original to avoid accumulating circles
    state.working_doc = loader.copy_dxf(state.original_doc)
    if GENERATED_LAYER not in state.working_doc.layers:
        state.working_doc.layers.add(GENERATED_LAYER)

    state.generated_handles = []
    state.generated_ray_handles = []

    if state.selected_chain:
        try:
            circle_handles, ray_handles = circle_generator.generate_circles(
                state.working_doc,
                state.selected_chain,
                state.params,
                closed=state.chain_info.get("is_closed", False),
            )
            state.generated_handles = circle_handles
            state.generated_ray_handles = ray_handles
        except Exception as e:
            # Log error; keep working_doc as original
            print(f"生成圆失败: {e}")

    # Use fixed view bounds based on original drawing, plus padding for generated circles.
    # This ensures the original drawing does not shift when parameters change.
    bounds = _padded_bounds(state.original_bounds, state.params)

    svg_result = svg_exporter.doc_to_svg(
        state.working_doc,
        selected_chain=state.selected_chain,
        bounds=bounds,
    )
    state.svg_string_generated = svg_result.svg_string
    state.entity_svg_transform = svg_result.transform

    # Original view: original doc with selection highlights but no generated circles
    original_result = svg_exporter.doc_to_svg(
        state.original_doc,
        selected_chain=state.selected_chain,
        bounds=bounds,
    )
    state.svg_string_original = original_result.svg_string


def _padded_bounds(original_bounds: dict, params: CircleParams) -> dict:
    """Keep viewBox fixed to original drawing bounds so the original graphic never shifts."""
    return original_bounds


def _svg_update_payload(state: SessionState):
    svg = state.svg_string_generated if state.show_generated else state.svg_string_original
    return {
        "type": "svg_update",
        "data": {
            "svg_content": svg,
            "selected_handles": state.selected_handles,
            "selected_chain": state.selected_chain,
            "chain_info": state.chain_info,
            "generated_count": len(state.generated_handles),
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
                svg_x = float(data.get("svg_x", 0))
                svg_y = float(data.get("svg_y", 0))
                append = bool(data.get("append", False))

                handle = _select_handle(state, data)
                if not handle:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "未找到 nearby 实体"},
                    })
                    continue

                if not append:
                    state.selected_handles = []
                if handle not in state.selected_handles:
                    state.selected_handles.append(handle)

                chain = path_analyzer.build_chain(state.working_doc, state.selected_handles)
                state.selected_chain = chain
                state.chain_info = path_analyzer.get_chain_info(state.working_doc, chain)
                regenerate(state)

                await websocket.send_json(_svg_update_payload(state))

            elif msg_type == "params_change":
                state.params = CircleParams.from_dict(data.get("params", {}))
                regenerate(state)
                await websocket.send_json(_svg_update_payload(state))

            elif msg_type == "toggle_preview":
                state.show_generated = bool(data.get("show_generated", True))
                await websocket.send_json(_svg_update_payload(state))

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
