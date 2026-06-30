"""Windows desktop launcher for the DXF auto shape web service.

The launcher uses only the Python standard library for the desktop window.
It starts the FastAPI/Uvicorn service as a child process, displays local/LAN
URLs, keeps a bounded live log buffer, and stops the service when the window
closes. The same file can be used as a PyInstaller entry point later: the
launcher process spawns itself with ``--service-child`` for the web service.
"""

from __future__ import annotations

import argparse
import collections
import ipaddress
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext


APP_TITLE = "DXF自动图形工具"
DEFAULT_PORT = int(os.environ.get("PORT", "8000"))
SERVICE_HOST = "0.0.0.0"
LOG_BUFFER_LINES = 2000
LOG_RENDER_LINES = 600


def _app_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _service_child(host: str, port: int) -> None:
    os.chdir(_app_dir())
    sys.path.insert(0, str(_app_dir()))
    os.environ["HOST"] = host
    os.environ["PORT"] = str(port)

    import uvicorn

    uvicorn.run(
        "backend.app:app",
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )


def _lan_ip() -> str:
    ps_ip = _lan_ip_from_windows_adapters()
    if ps_ip:
        return ps_ip

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if _is_lan_ipv4(ip):
                return ip
        finally:
            sock.close()
    except OSError:
        pass

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if _is_lan_ipv4(ip):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def _is_lan_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.version != 4:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    if ip in ipaddress.ip_network("198.18.0.0/15"):
        return False
    return True


def _lan_ip_score(value: str, alias: str = "", description: str = "") -> int:
    if not _is_lan_ipv4(value):
        return -1
    ip = ipaddress.ip_address(value)
    text = f"{alias} {description}".lower()
    score = 10
    if ip.is_private:
        score += 100
    if value.startswith("192.168."):
        score += 40
    elif value.startswith("10."):
        score += 30
    elif ip in ipaddress.ip_network("172.16.0.0/12"):
        score += 30
    virtual_words = (
        "virtual", "vmware", "virtualbox", "hyper-v", "wsl", "docker",
        "tap", "loopback", "vpn", "meta", "clash", "tailscale", "zerotier",
    )
    if any(word in text for word in virtual_words):
        score -= 80
    if "wi-fi" in text or "wifi" in text or "wlan" in text:
        score += 15
    if "ethernet" in text or "以太网" in text:
        score += 10
    return score


def _lan_ip_from_windows_adapters() -> str | None:
    if os.name != "nt":
        return None
    script = (
        "$items = Get-NetIPConfiguration | "
        "Where-Object { $_.IPv4Address -and $_.IPv4DefaultGateway } | "
        "ForEach-Object { [pscustomobject]@{ "
        "Alias=$_.InterfaceAlias; Description=$_.InterfaceDescription; "
        "IPv4=($_.IPv4Address | Select-Object -First 1).IPAddress; "
        "Gateway=($_.IPv4DefaultGateway | Select-Object -First 1).NextHop } }; "
        "$items | ConvertTo-Json -Compress"
    )
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            encoding="utf-8",
            errors="ignore",
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=3,
        ).strip()
    except Exception:
        return None
    if not output:
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]

    best_ip = None
    best_score = -1
    for item in data:
        ip = str(item.get("IPv4") or "")
        score = _lan_ip_score(
            ip,
            str(item.get("Alias") or ""),
            str(item.get("Description") or ""),
        )
        if score > best_score:
            best_ip = ip
            best_score = score
    return best_ip if best_score >= 0 else None


def _port_pids(port: int) -> set[int]:
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return set()

    pids: set[int] = set()
    needle = f":{port}"
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        state = parts[3]
        pid_text = parts[-1]
        if state.upper() != "LISTENING":
            continue
        if not local_address.endswith(needle):
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid != os.getpid():
            pids.add(pid)
    return pids


def _kill_pid(pid: int) -> bool:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return True
    except Exception:
        return False


class LauncherApp:
    def __init__(self, root: tk.Tk, port: int = DEFAULT_PORT) -> None:
        self.root = root
        self.port = port
        self.process: subprocess.Popen[str] | None = None
        self.log_lines: collections.deque[str] = collections.deque(maxlen=LOG_BUFFER_LINES)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_window: tk.Toplevel | None = None
        self.log_text: scrolledtext.ScrolledText | None = None
        self.lan_ip = _lan_ip()

        self.root.title(APP_TITLE)
        self.root.geometry("560x340")
        self.root.minsize(520, 320)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_ui()
        self._set_status(False, "未运行")
        self.root.after(200, self._drain_logs)
        self.root.after(500, self._poll_process)
        self.start_service()

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def lan_url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/"

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = tk.Frame(self.root, padx=22, pady=18)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)

        title = tk.Label(
            main,
            text=APP_TITLE,
            font=("Microsoft YaHei UI", 16, "bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="ew")

        status_row = tk.Frame(main)
        status_row.grid(row=1, column=0, sticky="ew", pady=(18, 8))
        self.status_dot = tk.Canvas(status_row, width=16, height=16, highlightthickness=0)
        self.status_dot.pack(side="left")
        self.status_circle = self.status_dot.create_oval(3, 3, 13, 13, fill="#c62828", outline="")
        self.status_label = tk.Label(status_row, text="未运行", font=("Microsoft YaHei UI", 11))
        self.status_label.pack(side="left", padx=(8, 0))

        urls = tk.LabelFrame(main, text="访问网址", padx=12, pady=10)
        urls.grid(row=2, column=0, sticky="ew", pady=(8, 14))
        urls.columnconfigure(1, weight=1)

        tk.Label(urls, text="本机访问：").grid(row=0, column=0, sticky="w", pady=3)
        self.local_url_var = tk.StringVar(value=self.local_url)
        tk.Entry(urls, textvariable=self.local_url_var, state="readonly").grid(row=0, column=1, sticky="ew", pady=3)

        tk.Label(urls, text="局域网访问：").grid(row=1, column=0, sticky="w", pady=3)
        self.lan_url_var = tk.StringVar(value=self.lan_url)
        tk.Entry(urls, textvariable=self.lan_url_var, state="readonly").grid(row=1, column=1, sticky="ew", pady=3)

        hint = tk.Label(
            main,
            text="同一局域网设备可访问上面的局域网网址。若无法访问，请检查 Windows 防火墙是否允许此程序通信。",
            wraplength=500,
            justify="left",
            fg="#555555",
            anchor="w",
        )
        hint.grid(row=3, column=0, sticky="ew", pady=(0, 14))

        buttons = tk.Frame(main)
        buttons.grid(row=4, column=0, sticky="ew")
        for i in range(4):
            buttons.columnconfigure(i, weight=1)

        self.toggle_button = tk.Button(buttons, text="运行服务", command=self.toggle_service, height=2)
        self.toggle_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.open_button = tk.Button(buttons, text="打开网页", command=self.open_web, height=2)
        self.open_button.grid(row=0, column=1, sticky="ew", padx=4)

        self.log_button = tk.Button(buttons, text="网站日志", command=self.open_logs, height=2)
        self.log_button.grid(row=0, column=2, sticky="ew", padx=4)

        self.quit_button = tk.Button(buttons, text="关闭程序", command=self.on_close, height=2)
        self.quit_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))

    def _log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {text.rstrip()}\n")

    def _set_status(self, running: bool, text: str) -> None:
        color = "#2e7d32" if running else "#c62828"
        self.status_dot.itemconfigure(self.status_circle, fill=color)
        self.status_label.configure(text=text)
        self.toggle_button.configure(text="停止运行" if running else "运行服务")
        self.open_button.configure(state=("normal" if running else "disabled"))

    def _service_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--service-child", "--host", SERVICE_HOST, "--port", str(self.port)]
        return [
            sys.executable,
            str(Path(__file__).resolve()),
            "--service-child",
            "--host",
            SERVICE_HOST,
            "--port",
            str(self.port),
        ]

    def start_service(self) -> None:
        if self.process and self.process.poll() is None:
            return

        for pid in sorted(_port_pids(self.port)):
            self._log(f"检测到端口 {self.port} 已被进程 {pid} 占用，正在关闭旧实例...")
            _kill_pid(pid)

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["HOST"] = SERVICE_HOST
        env["PORT"] = str(self.port)

        try:
            self.process = subprocess.Popen(
                self._service_command(),
                cwd=str(_app_dir()),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            self.process = None
            self._set_status(False, "启动失败")
            self._log(f"启动失败：{exc}")
            messagebox.showerror(APP_TITLE, f"服务启动失败：\n{exc}")
            return

        self._log(f"服务正在启动：{self.local_url}")
        self._log(f"局域网访问网址：{self.lan_url}")
        self._set_status(True, "运行中")

        if self.process.stdout:
            threading.Thread(
                target=self._read_process_output,
                args=(self.process.stdout,),
                daemon=True,
            ).start()

    def stop_service(self) -> None:
        if not self.process or self.process.poll() is not None:
            self.process = None
            self._set_status(False, "未运行")
            return

        self._log("正在停止服务...")
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_pid(self.process.pid)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        except Exception as exc:
            self._log(f"停止服务时出错：{exc}")
        finally:
            self.process = None
            self._set_status(False, "未运行")
            self._log("服务已停止")

    def toggle_service(self) -> None:
        if self.process and self.process.poll() is None:
            self.stop_service()
        else:
            self.start_service()

    def open_web(self) -> None:
        webbrowser.open(self.local_url)

    def open_logs(self) -> None:
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
            return

        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("网站日志")
        self.log_window.geometry("860x520")
        self.log_window.minsize(620, 360)
        self.log_window.columnconfigure(0, weight=1)
        self.log_window.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            self.log_window,
            wrap="word",
            font=("Consolas", 10),
            state="normal",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        snapshot = list(self.log_lines)[-LOG_RENDER_LINES:]
        if len(self.log_lines) > LOG_RENDER_LINES:
            self.log_text.insert("end", f"... 已省略更早的 {len(self.log_lines) - LOG_RENDER_LINES} 行日志 ...\n")
        self.log_text.insert("end", "".join(snapshot))
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

        self.log_window.protocol("WM_DELETE_WINDOW", self._close_logs)

    def _close_logs(self) -> None:
        if self.log_window:
            self.log_window.destroy()
        self.log_window = None
        self.log_text = None

    def _append_log_text(self, text: str) -> None:
        if not self.log_text or not self.log_window or not self.log_window.winfo_exists():
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        current_lines = int(float(self.log_text.index("end-1c").split(".")[0]))
        if current_lines > LOG_RENDER_LINES + 100:
            self.log_text.delete("1.0", "101.0")
            self.log_text.insert("1.0", "... 已自动裁剪较早日志，完整最近日志仍保留在程序内存中 ...\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _read_process_output(self, stream) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                self._log(line)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _drain_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_lines.append(line)
            self._append_log_text(line)
        self.root.after(200, self._drain_logs)

    def _poll_process(self) -> None:
        if self.process:
            code = self.process.poll()
            if code is not None:
                self._log(f"服务进程已退出，退出码：{code}")
                self.process = None
                self._set_status(False, "未运行")
        self.root.after(800, self._poll_process)

    def on_close(self) -> None:
        self.stop_service()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-child", action="store_true")
    parser.add_argument("--host", default=SERVICE_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    if args.service_child:
        _service_child(args.host, args.port)
        return

    root = tk.Tk()
    LauncherApp(root, port=args.port)
    root.mainloop()


if __name__ == "__main__":
    main()
