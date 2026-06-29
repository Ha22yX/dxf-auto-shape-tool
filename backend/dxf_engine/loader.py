import io
import ezdxf


def load_dxf(path: str) -> ezdxf.document.Drawing:
    return ezdxf.readfile(path)


def save_dxf(doc: ezdxf.document.Drawing, path: str) -> None:
    doc.saveas(path)


def copy_dxf(doc: ezdxf.document.Drawing) -> ezdxf.document.Drawing:
    """Create a deep copy of a DXF document via in-memory stream."""
    stream = io.StringIO()
    doc.write(stream)
    stream.seek(0)
    return ezdxf.read(stream)
