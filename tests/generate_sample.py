"""Generate a sample DXF for manual testing."""
import ezdxf
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_sample_dxf(path: str):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # A closed rectangle made of 4 separate lines
    msp.add_line((0, 0), (100, 0))
    msp.add_line((100, 0), (100, 80))
    msp.add_line((100, 80), (0, 80))
    msp.add_line((0, 80), (0, 0))

    # A separate LWPOLYLINE rectangle
    msp.add_lwpolyline([(120, 0), (220, 0), (220, 80), (120, 80)], close=True)

    # An arc edge (semicircle)
    msp.add_arc((300, 40), radius=40, start_angle=180, end_angle=360)
    msp.add_line((260, 40), (340, 40))  # close the arc to form a shape

    doc.saveas(path)
    print(f"Sample DXF saved to: {path}")


if __name__ == "__main__":
    output = os.path.join(os.path.dirname(__file__), "..", "temp", "sample.dxf")
    create_sample_dxf(os.path.abspath(output))
