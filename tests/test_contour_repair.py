"""End-to-end regressions for automatic completion of open DXF outlines."""
import asyncio
import io
from pathlib import Path
import ezdxf
import pytest
from fastapi import UploadFile
from shapely.geometry import Point
from backend.config import REPAIRED_OUTLINE_LAYER
from backend.dxf_engine.contour_repair import complete_outline
from backend.dxf_engine.outline import analyze_outline
from backend.dxf_engine import path_analyzer as paths
from backend.state import CircleParams, get_session
from backend.app import upload_dxf, select_entity, update_params, download_dxf, clear_session, websocket_endpoint


def assert_simple_closed(doc, repair):
    assert analyze_outline(doc, repair.chain).ready
    assert paths.get_chain_info(doc, repair.chain)["is_closed"]
    for connection in repair.connections:
        entity = doc.entitydb[connection["handle"]]
        assert entity.dxftype() == "LINE"
        assert entity.dxf.layer == REPAIRED_OUTLINE_LAYER


@pytest.mark.parametrize("reverse", [False, True])
def test_open_polyline_is_completed_with_actual_closing_edge(reverse):
    doc = ezdxf.new()
    points = [(0, 0), (200, 0), (200, 100), (0, 100)]
    if reverse:
        points.reverse()
    poly = doc.modelspace().add_lwpolyline(points)
    repair = complete_outline(doc, [poly.dxf.handle])
    assert_simple_closed(doc, repair)
    assert len(repair.connections) == 1
    assert repair.connections[0]["length"] == 100
    assert not poly.closed  # original geometry is preserved
    assert len(doc.modelspace()) == 2


def test_single_open_arc_gets_a_chord_instead_of_being_blocked():
    doc = ezdxf.new()
    arc = doc.modelspace().add_arc((0, 0), 100, 0, 180)
    repair = complete_outline(doc, [arc.dxf.handle])
    assert_simple_closed(doc, repair)
    assert len(repair.connections) == 1
    assert repair.connections[0]["length"] == pytest.approx(200)
    assert analyze_outline(doc, repair.chain).polygon.area == pytest.approx(3.14159265 * 10000 / 2, rel=.001)


def test_disconnected_edges_are_found_and_all_four_gaps_are_connected():
    doc = ezdxf.new()
    msp = doc.modelspace()
    first = msp.add_line((1, 0), (99, 0))
    others = [msp.add_line((100, 1), (100, 99)), msp.add_line((99, 100), (1, 100)), msp.add_line((0, 99), (0, 1))]
    repair = complete_outline(doc, [first.dxf.handle])
    assert_simple_closed(doc, repair)
    assert len(repair.connections) == 4
    assert repair.joined_entity_count == 3
    assert set([first.dxf.handle] + [edge.dxf.handle for edge in others]).issubset(repair.chain)


@pytest.mark.parametrize("reverse_second", [False, True])
def test_explicitly_selected_fragments_connect_across_larger_missing_spans(reverse_second):
    doc = ezdxf.new()
    left = doc.modelspace().add_lwpolyline([(0, 0), (0, 100), (40, 100)])
    points = [(60, 100), (100, 100), (100, 0)]
    right = doc.modelspace().add_lwpolyline(list(reversed(points)) if reverse_second else points)
    repair = complete_outline(doc, [left.dxf.handle, right.dxf.handle])
    assert_simple_closed(doc, repair)
    assert len(repair.connections) == 2
    assert sorted(round(connection["length"]) for connection in repair.connections) == [20, 100]


def test_neighboring_closed_hole_and_other_complete_board_are_not_absorbed():
    doc = ezdxf.new()
    poly = doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)])
    hole = doc.modelspace().add_circle((2, 2), 1)
    other = doc.modelspace().add_lwpolyline([(-3, 0), (-1, 0), (-1, 100), (-3, 100)], close=True)
    repair = complete_outline(doc, [poly.dxf.handle])
    assert_simple_closed(doc, repair)
    assert len(repair.connections) == 1
    assert hole.dxf.handle not in repair.chain
    assert other.dxf.handle not in repair.chain


def test_closed_outline_does_not_get_extra_connections():
    doc = ezdxf.new()
    poly = doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
    repair = complete_outline(doc, [poly.dxf.handle])
    assert_simple_closed(doc, repair)
    assert not repair.connections
    assert len(doc.modelspace()) == 1


def test_crossing_closure_attempt_is_rolled_back_without_leaving_lines():
    doc = ezdxf.new()
    poly = doc.modelspace().add_lwpolyline([(0, 0), (100, 100), (0, 100), (100, 0)])
    before = len(doc.modelspace())
    repair = complete_outline(doc, [poly.dxf.handle])
    assert not analyze_outline(doc, repair.chain).ready
    assert not repair.connections
    assert len(doc.modelspace()) == before


def test_single_line_without_a_region_is_not_artificially_turned_into_a_board():
    doc = ezdxf.new()
    line = doc.modelspace().add_line((0, 0), (100, 0))
    repair = complete_outline(doc, [line.dxf.handle])
    assert not repair.connections
    assert analyze_outline(doc, repair.chain).status == "open"
    assert len(doc.modelspace()) == 1


def test_horizontal_elevation_is_preserved_for_added_line():
    doc = ezdxf.new()
    poly = doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], dxfattribs={"elevation": 20})
    repair = complete_outline(doc, [poly.dxf.handle])
    assert_simple_closed(doc, repair)
    entity = doc.entitydb[repair.connections[0]["handle"]]
    assert entity.dxf.start.z == entity.dxf.end.z == 20


@pytest.mark.parametrize("fragmented", [False, True])
def test_web_preview_and_repeated_exports_share_the_same_completed_outline(fragmented):
    async def run():
        doc = ezdxf.new()
        m = doc.modelspace()
        if fragmented:
            first = m.add_line((1, 0), (199, 0))
            m.add_line((200, 1), (200, 99))
            m.add_line((199, 100), (1, 100))
            m.add_line((0, 99), (0, 1))
            expected_repairs = 4
        else:
            first = m.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)])
            expected_repairs = 1
        text = io.StringIO()
        doc.write(text)
        upload = await upload_dxf(UploadFile(filename="open-board.dxf", file=io.BytesIO(text.getvalue().encode())))
        sid = upload["session_id"]
        try:
            params = CircleParams(circle_radius=2, ray_offset=10, circles_per_ray=1, ray_count=24,
                                  top_gap_distance=0, air_duct_enabled=False)
            await update_params(sid, params.to_dict())
            result = await select_entity(sid, {"handle": first.dxf.handle})
            geometry = result["preview_geometry"]
            assert result["chain_info"]["is_closed"]
            assert not geometry["safety"]["blocked"]
            assert geometry["safety"]["repaired_edge_count"] == expected_repairs
            assert len(geometry["repaired_edges"]) == expected_repairs
            assert geometry["generated_count"] > 0
            state = get_session(sid)
            assert not list(state.original_doc.modelspace().query('LINE[layer=="AUTO_CLOSED_OUTLINE"]'))
            original_count = len(state.original_doc.modelspace())
            working_count = len(state.working_doc.modelspace())
            for _ in range(2):
                response = await download_dxf(sid)
                output = ezdxf.read(io.StringIO(response.body.decode()))
                connections = list(output.modelspace().query('LINE[layer=="AUTO_CLOSED_OUTLINE"]'))
                assert len(connections) == expected_repairs
                chain = paths.build_chain(output, [first.dxf.handle])
                region = analyze_outline(output, chain)
                assert region.ready
                exported = list(output.modelspace().query('CIRCLE[layer=="GENERATED_CIRCLES"]'))
                assert len(exported) == geometry["generated_count"]
                for circle in exported:
                    point = Point(circle.dxf.center.x, circle.dxf.center.y)
                    assert region.polygon.contains(point)
                    assert region.polygon.boundary.distance(point) >= circle.dxf.radius
                expected = sorted((round(c["cx"] / upload["scale"] + upload["bounds"]["min"][0], 6),
                                   round(upload["bounds"]["max"][1] - c["cy"] / upload["scale"], 6)) for c in geometry["circles"])
                actual = sorted((round(c.dxf.center.x, 6), round(c.dxf.center.y, 6)) for c in exported)
                assert actual == expected
                assert len(state.original_doc.modelspace()) == original_count
                assert len(state.working_doc.modelspace()) == working_count
            # Re-selection rebuilds repair edges rather than accumulating them.
            await select_entity(sid, {"handle": first.dxf.handle})
            assert len(state.auto_connections) == expected_repairs
            assert len(state.working_doc.modelspace()) == working_count

            from fastapi import WebSocketDisconnect
            class Socket:
                received = False
                sent = []
                async def accept(self): pass
                async def receive_json(self):
                    if self.received:
                        raise WebSocketDisconnect()
                    self.received = True
                    return {"type": "clear_selection", "data": {}}
                async def send_json(self, data): self.sent.append(data)
            socket = Socket()
            await websocket_endpoint(socket, sid)
            assert not state.auto_connections
            assert not state.selected_chain
            assert len(state.working_doc.modelspace()) == original_count
            assert socket.sent[0]["type"] == "cleared"
        finally:
            await clear_session(sid)
    asyncio.run(run())


def test_repository_open_board_is_completed_and_can_generate_inside_holes():
    from backend.dxf_engine import circle_generator
    source = next(path for path in (Path(__file__).resolve().parents[1] / "Test Files").iterdir() if "初学板" in path.name and path.suffix.lower() == ".dxf")
    doc = ezdxf.readfile(source)
    seed = next(iter(doc.modelspace())).dxf.handle
    before = paths.build_chain(doc, [seed])
    assert analyze_outline(doc, before).status == "open"
    repair = complete_outline(doc, [seed])
    assert_simple_closed(doc, repair)
    assert len(repair.connections) == 1
    region = analyze_outline(doc, repair.chain)
    min_x, min_y, max_x, max_y = region.polygon.bounds
    params = CircleParams(air_duct_enabled=False)
    result = circle_generator.compute_preview_geometry(doc, repair.chain, params, closed=True,
               bounds={"min": [min_x, min_y], "max": [max_x, max_y]}, scale=1, require_closed_outline=True)
    assert result["generated_count"] > 0
    for circle in result["circles"]:
        point = Point(circle["cx"] + min_x, max_y - circle["cy"])
        assert region.polygon.contains(point)
        assert region.polygon.boundary.distance(point) >= circle["r"]


def test_nearby_fragment_at_different_elevation_is_not_adopted():
    doc = ezdxf.new()
    first = doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)])
    foreign = doc.modelspace().add_line((0, 101, 50), (0, -1, 50))
    repair = complete_outline(doc, [first.dxf.handle])
    assert_simple_closed(doc, repair)
    assert foreign.dxf.handle not in repair.chain
    assert len(repair.connections) == 1
