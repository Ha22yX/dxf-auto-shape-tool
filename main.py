import os
import sys
import webbrowser
import threading
import time

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app import app
from backend.config import HOST, PORT


def open_browser():
    time.sleep(1.5)
    url = f"http://{HOST}:{PORT}"
    try:
        webbrowser.open(url)
    except Exception:
        print(f"请手动打开浏览器访问: {url}")


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT)
