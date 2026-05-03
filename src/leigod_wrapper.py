"""
雷神加速器 - 进程监控自动暂停
====================================
自动启动雷神客户端, 读取 leigod_config.yaml 配置,
根据监控进程列表自动暂停计时:
  - 列表中任一进程运行中 → 保持当前计时状态
  - 列表中全部进程都关闭 → 暂停计时

用法:
  python leigod_wrapper.py                     (读配置文件, 自动启动)
  python leigod_wrapper.py "game.exe"          (覆盖进程列表)
  python leigod_wrapper.py --no-launch         (不启动, 仅连接已有实例)

Ctrl+C 退出 (自动暂停计时)
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import ctypes

try:
    import requests
except ImportError:
    requests = None

try:
    import websocket
except ImportError:
    print("缺少依赖: websocket-client。请运行: pip install websocket-client")
    sys.exit(1)

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

try:
    import yaml
except ImportError:
    yaml = None


# ─────────────────────────────────────────────
# HTTP: requests
# ─────────────────────────────────────────────
def tcp_check(host: str, port: int, timeout: float = 2) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def leigod_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq leigod.exe", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            text=True,
        )
        return "leigod.exe" in out.lower()
    except Exception:
        return False


def relaunch_self_as_admin(log_file: str | None = None, force_relaunch: bool = False):
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = [*sys.argv[1:]]
    else:
        exe = sys.executable
        script = os.path.abspath(__file__)
        args = [script, *sys.argv[1:]]
    if force_relaunch and "--force-relaunch" not in args:
        args.append("--force-relaunch")
    if log_file and "--log-file" not in args:
        args.extend(["--log-file", log_file])
    params = " ".join(f'"{a}"' for a in args)
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        exe,
        params,
        get_app_dir(),
        1,
    )
    if rc <= 32:
        raise RuntimeError(f"请求管理员权限失败，ShellExecuteW 返回 {rc}")


def kill_leigod_processes():
    for image in ("leigod.exe", "leigod_launcher.exe", "leishenSdk.exe"):
        subprocess.run(
            ["taskkill", "/IM", image, "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )


def get_app_dir() -> str:
    """PyInstaller exe 模式返回 exe 所在目录；源码模式返回当前工作目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.getcwd()


def http_get(port: int, path: str = "/json", timeout: float = 5) -> tuple[int, str]:
    url = f"http://127.0.0.1:{port}{path}"
    if requests is None:
        return 0, "缺少依赖: requests。请运行: pip install requests"

    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 Chrome/120 Safari/537.36",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def raw_http_get(host: str, port: int, path: str = "/json", timeout: float = 5) -> tuple[int, str]:
    """最小 HTTP GET，避免某些 HTTP 客户端被 Electron 调试端口 reset 时卡住。

    仅用于本机 DevTools 端口探活；真正取 target 列表仍优先使用 http_get()。
    """
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "User-Agent: Mozilla/5.0 Chrome/120 Safari/537.36\r\n"
        "Accept: application/json,text/plain,*/*\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    data = b""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(request)
        while True:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk

    if not data:
        return 0, ""
    head, _, body = data.partition(b"\r\n\r\n")
    status_line = head.splitlines()[0].decode("iso-8859-1", errors="replace") if head else ""
    try:
        status = int(status_line.split()[1])
    except Exception:
        status = 0
    return status, body.decode("utf-8", errors="replace")


# ─────────────────────────────────────────────
# CDP 客户端
# ─────────────────────────────────────────────
class CDP:
    def __init__(self, port=9222, host="127.0.0.1"):
        self.port = port
        self.host = host
        self.ws = None
        self._id = 0

    def connect(self, timeout=10):
        status, body = http_get(self.port, "/json", timeout=5)
        if status != 200:
            raise ConnectionError(f"HTTP /json 返回 {status}: {body[:100]}")
        targets = json.loads(body)
        page = next((t for t in targets if t.get("type") == "page"), None)
        if not page:
            raise ConnectionError("未找到渲染进程页面")
        ws_url = page["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(ws_url, timeout=timeout)

    def eval(self, js, timeout=15):
        self._id += 1
        self.ws.send(json.dumps({
            "id": self._id,
            "method": "Runtime.evaluate",
            "params": {"expression": js, "returnByValue": True, "awaitPromise": True},
        }))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self.ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == self._id:
                r = msg.get("result", {}).get("result", {})
                if r.get("type") == "undefined":
                    return None
                if "value" in r:
                    return r["value"]
                if r.get("subtype") == "error":
                    raise RuntimeError(r.get("description", "JS error"))
                return None
        raise TimeoutError("CDP eval timeout")

    def invoke(self, channel, *args, timeout=15):
        args_json = json.dumps(list(args), ensure_ascii=False)
        js = f"""
        (async () => {{
            try {{
                const r = await window.leigodSimplify.invoke("{channel}", ...{args_json});
                return JSON.stringify({{ok:true, data:r}});
            }} catch(e) {{
                let detail = "";
                try {{ detail = JSON.stringify(e); }} catch(_) {{}}
                return JSON.stringify({{ok:false, error:String(e), msg:e?.message||"", detail}});
            }}
        }})()
        """
        raw = self.eval(js, timeout=timeout)
        if raw is None:
            return {"ok": False, "error": "null"}
        return json.loads(raw) if isinstance(raw, str) else raw

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass


# ─────────────────────────────────────────────
# 进程检测
# ─────────────────────────────────────────────
def check_processes(names: set[str]) -> dict[str, bool]:
    result = {n: False for n in names}
    try:
        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            text=True,
        )
        running = set()
        for line in out.splitlines():
            parts = line.split('","')
            if parts:
                running.add(parts[0].strip('"').lower())
        for n in names:
            result[n] = n.lower() in running
    except Exception as e:
        print(f"  [!] tasklist 失败: {e}")
    return result


# ─────────────────────────────────────────────
# 启动 / 连接
# ─────────────────────────────────────────────
def launch(exe: str, port: int):
    if not os.path.exists(exe):
        print(f"[-] 找不到雷神: {exe}")
        sys.exit(1)
    # leigod.exe 直接启动需要 launcher 注入的 -launch/-sdkpid 参数；
    # 实测 leigod_launcher.exe 不会正确转发 Chromium 调试参数，且带参数
    # 启动时可能直接退出。若已通过 patch_leigod_debug.py 给 app.asar
    # 注入了 remote-debugging-port，则 launcher 无需任何参数。
    if os.path.basename(exe).lower() == "leigod_launcher.exe":
        args = []
    else:
        args = [f"--remote-debugging-port={port}", "--remote-allow-origins=*"]
    print(f"[*] 启动: {exe}" + (f" {' '.join(args)}" if args else ""))
    try:
        proc = subprocess.Popen(
            [exe, *args],
            cwd=os.path.dirname(exe),
        )
        print(f"[*] PID={proc.pid}")
    except OSError as e:
        # 雷神安装在 Program Files 且带管理员 manifest 时，CreateProcess 会返回
        # WinError 740。这里改用 ShellExecute/Start-Process 触发 UAC，让用户确认
        # 后继续等待 DevTools 端口。
        if getattr(e, "winerror", None) != 740:
            raise
        print("[!] 该程序需要管理员权限，正在通过 UAC 提权启动...")
        ps = (
            "Start-Process "
            f"-FilePath {json.dumps(exe)} "
            f"-ArgumentList {json.dumps(' '.join(args))} "
            f"-WorkingDirectory {json.dumps(os.path.dirname(exe))} "
            "-Verb RunAs"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=True,
            creationflags=0x08000000,
        )
        print("[*] 已提交启动请求，请在 UAC 弹窗中选择“是”。")


def wait_port(port: int, timeout=30) -> bool:
    print(f"[*] 等待端口 {port} 就绪...")
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        # 先检查 TCP
        if not tcp_check("127.0.0.1", port):
            time.sleep(1)
            continue
        # TCP 通了, 尝试 HTTP
        try:
            status, body = raw_http_get("127.0.0.1", port, "/json", timeout=3)
            if status == 200 and body.strip():
                print(f"[+] 端口 {port} 就绪 (HTTP {status}, {len(body)} bytes)")
                return True
            print(f"    HTTP {status}, body={body[:80]}")
        except Exception as e:
            print(f"    HTTP 异常: {type(e).__name__}: {e}")
        time.sleep(1)
    return False


def connect(port: int, retries=5, interval=5) -> CDP:
    for i in range(1, retries + 1):
        try:
            cdp = CDP(port)
            cdp.connect()
            print(f"[+] 已连接 (尝试 {i}/{retries})")
            return cdp
        except Exception as e:
            print(f"  [-] 连接失败 ({i}/{retries}): {e}")
            if i < retries:
                time.sleep(interval)
    print("[-] 无法连接, 退出。")
    sys.exit(1)


# ─────────────────────────────────────────────
# 登录
# ─────────────────────────────────────────────
def auto_login(cdp: CDP, mobile: str, password: str, country: str = "86") -> bool:
    info = cdp.invoke("get-login-info")
    if info.get("ok") and info.get("data"):
        d = info["data"]
        if d.get("user_token") or d.get("token"):
            print(f"[+] 已登录: {d.get('nickname', d.get('mobile_num', '?'))}")
            return True
    pwd_enc = hashlib.md5(password.encode()).hexdigest()
    result = cdp.invoke("login", {
        "mobile_num": mobile, "country_code": country,
        "password": pwd_enc, "user_type": 0,
        "remember": 1, "autologin": 1, "device_info": "Windows",
    })
    if result.get("ok"):
        print("[+] 登录成功!")
        return True
    print(f"[-] 登录失败: {result.get('msg') or result.get('error')}")
    return False


# ─────────────────────────────────────────────
# 配置加载
# ─────────────────────────────────────────────
def load_config(path: str) -> dict:
    if yaml is not None:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}

    cfg = {}
    in_list = False
    list_key = None
    list_vals = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                if in_list and list_vals:
                    cfg[list_key] = list_vals
                    in_list, list_vals = False, []
                continue
            if stripped.startswith("- ") and in_list:
                list_vals.append(stripped[2:].strip().strip('"').strip("'"))
                continue
            if ":" in stripped:
                if in_list and list_vals:
                    cfg[list_key] = list_vals
                    list_vals = []
                    in_list = False
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if not val:
                    in_list, list_key = True, key
                else:
                    try:
                        cfg[key] = int(val)
                    except ValueError:
                        cfg[key] = val if val.lower() not in ("true", "false") else val.lower() == "true"

    if in_list and list_vals:
        cfg[list_key] = list_vals
    return cfg


# ─────────────────────────────────────────────
# 主监控循环 (支持配置热重载)
# ─────────────────────────────────────────────
class WatchState:
    def __init__(self, processes, interval, show_time, config_path):
        self.processes = processes
        self.interval = interval
        self.show_time = show_time
        self.config_path = config_path
        self._mtime = self._get_mtime()

    def _get_mtime(self):
        try:
            return os.path.getmtime(self.config_path)
        except OSError:
            return 0

    def check_reload(self) -> bool:
        new_mtime = self._get_mtime()
        if new_mtime <= self._mtime:
            return False
        self._mtime = new_mtime
        try:
            cfg = load_config(self.config_path)
        except Exception as e:
            print(f"  [!] 配置重载失败: {e}")
            return False

        old_p, old_i, old_t = self.processes, self.interval, self.show_time

        if "watched_processes" in cfg:
            self.processes = cfg["watched_processes"]
        if "check_interval" in cfg:
            self.interval = cfg["check_interval"]
        if "show_time_info" in cfg:
            self.show_time = cfg["show_time_info"]

        changed = self.processes != old_p or self.interval != old_i or self.show_time != old_t
        if changed:
            print(f"\n  [{ts()}] 配置已重载")
            if self.processes != old_p:
                print(f"          进程: {', '.join(self.processes)} (原: {', '.join(old_p)})")
            if self.interval != old_i:
                print(f"          间隔: {self.interval}s (原: {old_i}s)")
        return changed


def monitor(cdp: CDP, state: WatchState):
    paused = None
    # 首次启动不立即扫描，等待一个完整 interval 后再执行第一次进程检查。
    last_check = time.monotonic()

    print(f"\n{'='*55}")
    print(f"  监控: {', '.join(state.processes)}")
    print(f"  间隔: {state.interval}s   全关→暂停 | 任一开→保持当前状态")
    print(f"{'='*55}")
    print(f"  Ctrl+C 退出时会尝试暂停计时  |  修改配置文件自动生效\n")

    while True:
        state.check_reload()

        now = time.monotonic()
        effective_interval = min(state.interval, 2)

        if now - last_check >= state.interval:
            last_check = now
            try:
                names = set(state.processes)
                status = check_processes(names)
                any_running = any(status.values())

                if any_running:
                    if paused is not False:
                        running = [n for n, ok in status.items() if ok]
                        print(f"  [{ts()}] 检测到运行中进程: {', '.join(running)}，不执行计时切换")
                    paused = False

                elif not any_running and paused is not True:
                    result = cdp.invoke("pause-user-time")
                    if result.get("ok"):
                        print(f"  [{ts()}] 暂停  所有进程已关闭")
                    else:
                        print(f"  [{ts()}] 暂停失败: {result.get('msg') or result.get('detail') or result.get('error')}")
                    paused = True

                if state.show_time and paused is not None:
                    try:
                        info = cdp.invoke("refresh-user-time-info", timeout=5)
                        if info.get("ok") and info.get("data"):
                            remaining = info["data"].get("remaining_time", "")
                            if remaining:
                                label = "暂停" if paused else "保持"
                                print(f"  [{ts()}]   {label}  余额={remaining}")
                    except Exception:
                        pass

            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"  [{ts()}] 异常: {e}")
                if "Connection" in str(e) or "timed out" in str(e):
                    print("  [*] 重连中...")
                    try:
                        cdp.close()
                    except Exception:
                        pass
                    try:
                        cdp = connect(cdp.port, retries=3, interval=3)
                    except SystemExit:
                        break

        time.sleep(effective_interval)


def ts():
    return time.strftime("%H:%M:%S")


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="雷神加速器 - 进程监控自动暂停",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
配置文件 leigod_config.yaml (与脚本同目录) 会被自动读取。
命令行参数会覆盖配置文件中的值。

示例:
  python leigod_wrapper.py                        # 读配置, 自动启动
  python leigod_wrapper.py --admin                 # 管理员方式运行/重启客户端
  python leigod_wrapper.py --force-relaunch        # 关闭已有雷神并用调试端口重启
  python leigod_wrapper.py "game.exe" "app.exe"   # 覆盖进程列表
  python leigod_wrapper.py --no-launch            # 仅连接已有实例
  python leigod_wrapper.py --interval 10          # 覆盖检查间隔
""",
    )
    parser.add_argument("processes", nargs="*", help="覆盖监控进程列表")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径")
    parser.add_argument("--interval", type=int, default=None, help="检查间隔")
    parser.add_argument("--mobile", default=None, help="手机号")
    parser.add_argument("--password", default=None, help="密码")
    parser.add_argument("--country", default=None, help="区号")
    parser.add_argument("--exe", default=None, help="雷神路径")
    parser.add_argument("--port", type=int, default=None, help="调试端口")
    parser.add_argument("--no-launch", action="store_true", help="不启动客户端")
    parser.add_argument("--force-relaunch", action="store_true", help="强制关闭已有雷神后重新用调试端口启动")
    parser.add_argument("--admin", action="store_true", help="以管理员权限重新启动本脚本")
    parser.add_argument("--no-admin", action="store_true", help="不自动请求管理员权限")
    parser.add_argument("--log-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-time-info", action="store_true", help="不打印时间余额")
    parser.add_argument("--tray", action="store_true", help="登录后最小化")

    args = parser.parse_args()

    if args.log_file:
        log_fp = open(args.log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_fp
        sys.stderr = log_fp
        print(f"\n\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} elevated run =====")

    # 源码模式默认自动提权；PyInstaller 版本通过 manifest 在启动前请求管理员权限，
    # 避免运行后再重启导致 stdout/stderr 丢失。
    if (not getattr(sys, "frozen", False)) and not args.no_admin and not is_admin():
        print("[*] 正在请求管理员权限重新启动...")
        relaunch_self_as_admin(os.path.join(get_app_dir(), "leigod_wrapper_admin.log"))
        return

    script_dir = get_app_dir()
    config_path = args.config or os.path.join(script_dir, "leigod_config.yaml")

    cfg = {}
    if os.path.exists(config_path):
        print(f"[*] 读取配置: {config_path}")
        cfg = load_config(config_path)
    else:
        print(f"[!] 配置不存在: {config_path}")

    processes = args.processes or cfg.get("watched_processes", [])
    interval = args.interval or cfg.get("check_interval", 5)
    mobile = args.mobile or cfg.get("login_mobile", "")
    password = args.password or cfg.get("login_password", "")
    country = args.country or cfg.get("login_country", "86")
    port = args.port or cfg.get("debug_port", 9222)
    exe = args.exe or cfg.get("leigod_exe", r"C:\Program Files (x86)\LeiGod_Acc\leigod_launcher.exe")
    retries = cfg.get("connect_retries", 5)
    retry_interval = cfg.get("connect_retry_interval", 5)

    if not password:
        mobile = ""

    if not processes:
        print("[-] 无监控进程! 请在配置文件中设置 watched_processes 或通过命令行指定。")
        sys.exit(1)

    print()
    print("=" * 55)
    print("  雷神加速器 · 进程监控自动暂停")
    print("=" * 55)
    print(f"  监控: {', '.join(processes)}")
    print(f"  间隔: {interval}s")
    print(f"  登录: {'是 (' + mobile + ')' if mobile else '否 (已有登录态)'}")
    print()

    # 启动
    if not args.no_launch:
        if args.force_relaunch:
            if not is_admin():
                print("[!] 强制重启雷神需要管理员权限，正在请求 UAC...")
                relaunch_self_as_admin(os.path.join(script_dir, "leigod_wrapper_admin.log"), force_relaunch=True)
                return
            print("[*] 正在关闭已有雷神进程...")
            kill_leigod_processes()
            time.sleep(3)

        # 先检查是否已经在运行
        if tcp_check("127.0.0.1", port):
            print(f"[*] 端口 {port} 已有服务, 跳过启动")
        else:
            if leigod_running() and not args.force_relaunch:
                print(f"[!] 检测到雷神已在运行，但调试端口 {port} 未开启。")
                print("    Electron 调试端口只能在启动时开启，需关闭后重启。")
                if not is_admin():
                    print("    正在请求管理员权限重启脚本并强制重启雷神...")
                    relaunch_self_as_admin(os.path.join(script_dir, "leigod_wrapper_admin.log"), force_relaunch=True)
                    return
                print("    将强制关闭已有雷神后重启。")
                kill_leigod_processes()
                time.sleep(3)
            launch(exe, port)
            if not wait_port(port, timeout=30):
                print(f"[!] 端口 {port} 探活超时，继续尝试 CDP 连接...")

    # 连接
    cdp = connect(port, retries=retries, interval=retry_interval)

    # 登录
    if mobile and password:
        for attempt in range(1, 4):
            if auto_login(cdp, mobile, password, country):
                break
            if attempt < 3:
                print(f"  3 秒后重试 ({attempt}/3)...")
                time.sleep(3)
        else:
            print("[!] 登录未成功, 继续监控。")

    # 最小化
    if args.tray:
        try:
            cdp.invoke("hide-window-to-tray")
        except Exception:
            try:
                cdp.invoke("minimize-window")
            except Exception:
                pass

    def pause_on_exit():
        try:
            result = cdp.invoke("pause-user-time", timeout=8)
            if result.get("ok"):
                print("[*] 退出前已暂停计时")
            else:
                print(f"[*] 退出前暂停计时请求已发送但返回失败: {result.get('msg') or result.get('detail') or result.get('error')}")
        except Exception as e:
            print(f"[*] 退出前暂停计时异常: {e}")

    # 退出时无论如何尝试暂停
    def on_exit(sig, frame):
        print("\n[*] 退出...")
        pause_on_exit()
        cdp.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_exit)
    signal.signal(signal.SIGTERM, on_exit)

    state = WatchState(processes, interval, show_time=not args.no_time_info, config_path=config_path)
    try:
        monitor(cdp, state)
    finally:
        pause_on_exit()
        cdp.close()


if __name__ == "__main__":
    main()
