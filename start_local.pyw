"""Desktop entry point with visible startup errors, even under pythonw.exe."""
from pathlib import Path
import ctypes
import os
import traceback

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ.setdefault("XDG_CONFIG_HOME", str(ROOT / "temp" / "config"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "temp" / "cache"))

if __name__ == "__main__":
    try:
        from launcher import main
        main()
    except Exception:
        error = traceback.format_exc()
        log = ROOT / "temp" / "startup-error.log"
        try:
            log.parent.mkdir(exist_ok=True)
            log.write_text(error, encoding="utf-8")
        except OSError:
            pass
        ctypes.windll.user32.MessageBoxW(None, f"程序启动失败。\n\n{error[-1800:]}\n错误日志：{log}", "DXF 自动图形工具", 0x10)
        raise SystemExit(1)
