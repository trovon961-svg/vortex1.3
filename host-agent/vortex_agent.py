"""Vortex Host Agent: recebe controles do navegador (localhost) e injeta no Windows."""
import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys

import websockets

IS_WIN = sys.platform == "win32"

# ---------------------------------------------------------------- teclado/mouse
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def _send(inp):
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    # KeyboardEvent.code -> (scancode, extended)
    SC = {"Escape": 1, "Digit1": 2, "Digit2": 3, "Digit3": 4, "Digit4": 5, "Digit5": 6, "Digit6": 7,
          "Digit7": 8, "Digit8": 9, "Digit9": 10, "Digit0": 11, "Minus": 12, "Equal": 13, "Backspace": 14,
          "Tab": 15, "KeyQ": 16, "KeyW": 17, "KeyE": 18, "KeyR": 19, "KeyT": 20, "KeyY": 21, "KeyU": 22,
          "KeyI": 23, "KeyO": 24, "KeyP": 25, "BracketLeft": 26, "BracketRight": 27, "Enter": 28,
          "ControlLeft": 29, "KeyA": 30, "KeyS": 31, "KeyD": 32, "KeyF": 33, "KeyG": 34, "KeyH": 35,
          "KeyJ": 36, "KeyK": 37, "KeyL": 38, "Semicolon": 39, "Quote": 40, "Backquote": 41,
          "ShiftLeft": 42, "Backslash": 43, "KeyZ": 44, "KeyX": 45, "KeyC": 46, "KeyV": 47, "KeyB": 48,
          "KeyN": 49, "KeyM": 50, "Comma": 51, "Period": 52, "Slash": 53, "ShiftRight": 54,
          "NumpadMultiply": 55, "AltLeft": 56, "Space": 57, "CapsLock": 58, "F1": 59, "F2": 60, "F3": 61,
          "F4": 62, "F5": 63, "F6": 64, "F7": 65, "F8": 66, "F9": 67, "F10": 68, "F11": 87, "F12": 88,
          "Numpad7": 71, "Numpad8": 72, "Numpad9": 73, "NumpadSubtract": 74, "Numpad4": 75, "Numpad5": 76,
          "Numpad6": 77, "NumpadAdd": 78, "Numpad1": 79, "Numpad2": 80, "Numpad3": 81, "Numpad0": 82,
          "NumpadDecimal": 83, "IntlBackslash": 86}
    SC_EXT = {"ControlRight": 29, "AltRight": 56, "ArrowUp": 72, "ArrowDown": 80, "ArrowLeft": 75,
              "ArrowRight": 77, "Insert": 82, "Delete": 83, "Home": 71, "End": 79, "PageUp": 73,
              "PageDown": 81, "NumpadEnter": 28, "NumpadDivide": 53, "MetaLeft": 91, "MetaRight": 92}

    def key(code, down):
        ext = code in SC_EXT
        sc = SC_EXT.get(code) or SC.get(code)
        if not sc:
            return
        flags = 0x0008 | (0 if down else 0x0002) | (0x0001 if ext else 0)
        _send(INPUT(type=1, u=_U(ki=KEYBDINPUT(0, sc, flags, 0, 0))))

    def mouse_move(dx, dy):
        _send(INPUT(type=0, u=_U(mi=MOUSEINPUT(int(dx), int(dy), 0, 0x0001, 0, 0))))

    def mouse_abs(x, y):
        nx, ny = int(max(0, min(1, x)) * 65535), int(max(0, min(1, y)) * 65535)
        _send(INPUT(type=0, u=_U(mi=MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8000 | 0x4000, 0, 0))))

    BTN = {0: (0x0002, 0x0004), 1: (0x0020, 0x0040), 2: (0x0008, 0x0010)}

    def mouse_button(b, down):
        f = BTN.get(b)
        if f:
            _send(INPUT(type=0, u=_U(mi=MOUSEINPUT(0, 0, 0, f[0] if down else f[1], 0, 0))))

    def mouse_wheel(dy):
        _send(INPUT(type=0, u=_U(mi=MOUSEINPUT(0, 0, ctypes.c_ulong(int(-dy)).value, 0x0800, 0, 0))))
else:
    try:
        from pynput import keyboard as _kb, mouse as _ms
        _k, _m = _kb.Controller(), _ms.Controller()
    except Exception as e:  # sem display gráfico
        print(f"[aviso] teclado/mouse desativados ({e})")
        _kb = _ms = _k = _m = None

    def _pk(code):
        if code.startswith("Key"):
            return code[3:].lower()
        if code.startswith("Digit"):
            return code[5:]
        special = {"Space": "space", "Enter": "enter", "Escape": "esc", "Tab": "tab", "Backspace": "backspace",
                   "ShiftLeft": "shift", "ShiftRight": "shift_r", "ControlLeft": "ctrl", "ControlRight": "ctrl_r",
                   "AltLeft": "alt", "AltRight": "alt_r", "ArrowUp": "up", "ArrowDown": "down",
                   "ArrowLeft": "left", "ArrowRight": "right"}
        name = special.get(code) or (code.lower() if code.startswith("F") and code[1:].isdigit() else None)
        return getattr(_kb.Key, name) if name else None

    def key(code, down):
        if not _k:
            return
        k = _pk(code)
        if k is not None:
            (_k.press if down else _k.release)(k)

    def mouse_move(dx, dy):
        if _m:
            _m.move(int(dx), int(dy))

    def mouse_abs(x, y):
        pass

    def mouse_button(b, down):
        if not _m:
            return
        btn = {0: _ms.Button.left, 1: _ms.Button.middle, 2: _ms.Button.right}.get(b)
        if btn:
            (_m.press if down else _m.release)(btn)

    def mouse_wheel(dy):
        if _m:
            _m.scroll(0, -1 if dy > 0 else 1)

# ---------------------------------------------------------------- controle Xbox virtual
pads = {}
try:
    import vgamepad as vg

    XB = vg.XUSB_BUTTON
    GP_MAP = {0: XB.XUSB_GAMEPAD_A, 1: XB.XUSB_GAMEPAD_B, 2: XB.XUSB_GAMEPAD_X, 3: XB.XUSB_GAMEPAD_Y,
              4: XB.XUSB_GAMEPAD_LEFT_SHOULDER, 5: XB.XUSB_GAMEPAD_RIGHT_SHOULDER, 8: XB.XUSB_GAMEPAD_BACK,
              9: XB.XUSB_GAMEPAD_START, 10: XB.XUSB_GAMEPAD_LEFT_THUMB, 11: XB.XUSB_GAMEPAD_RIGHT_THUMB,
              12: XB.XUSB_GAMEPAD_DPAD_UP, 13: XB.XUSB_GAMEPAD_DPAD_DOWN, 14: XB.XUSB_GAMEPAD_DPAD_LEFT,
              15: XB.XUSB_GAMEPAD_DPAD_RIGHT, 16: XB.XUSB_GAMEPAD_GUIDE}
except Exception as e:  # ViGEmBus ausente ou SO sem suporte
    vg = None
    print(f"[aviso] controle virtual desativado ({e}). Instale ViGEmBus + 'pip install vgamepad'.")


def gamepad(slot, b, axes, lt, rt):
    if not vg:
        return
    pad = pads.get(slot)
    if pad is None:
        pad = pads[slot] = vg.VX360Gamepad()
    for idx, xb in GP_MAP.items():
        (pad.press_button if b & (1 << idx) else pad.release_button)(button=xb)
    lx, ly, rx, ry = (axes + [0, 0, 0, 0])[:4]
    pad.left_joystick_float(x_value_float=lx, y_value_float=-ly)
    pad.right_joystick_float(x_value_float=rx, y_value_float=-ry)
    pad.left_trigger_float(value_float=lt)
    pad.right_trigger_float(value_float=rt)
    pad.update()


# ---------------------------------------------------------------- janelas (Windows)
if IS_WIN:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]

    def list_windows():
        out = []

        def cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if not n:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append((hwnd, buf.value, r.right - r.left, r.bottom - r.top))
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return out

    def window_title(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def window_alive(hwnd):
        return bool(hwnd) and bool(user32.IsWindow(hwnd))

    def window_pid(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def focus(hwnd):
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 0x0002, 0)
        user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)
        user32.SetForegroundWindow(hwnd)

    def make_fullscreen(hwnd):
        """Deixa a janela sem bordas cobrindo o monitor inteiro (se ainda não estiver)."""
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
        m = mi.rcMonitor
        if r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom:
            return
        user32.ShowWindow(hwnd, 9)
        style = user32.GetWindowLongW(hwnd, -16) & ~0x00CF0000  # remove WS_OVERLAPPEDWINDOW
        user32.SetWindowLongW(hwnd, -16, style)
        user32.SetWindowPos(hwnd, 0, m.left, m.top, m.right - m.left, m.bottom - m.top, 0x0020 | 0x0040)
else:
    def list_windows():
        return []

    def window_title(hwnd):
        return ""

    def window_alive(hwnd):
        return False

    def window_pid(hwnd):
        return 0

    def focus(hwnd):
        pass

    def make_fullscreen(hwnd):
        pass


import threading
import time
from urllib.parse import urlencode

IGNORE_TITLES = ("steam", "vortex", "emergent", "chrome", "edge", "program manager", "configurações", "settings")
LAUNCH_EXT = (".exe", ".bat", ".cmd", ".lnk", ".url")
PROFILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VortexHost", "browser")


def find_browser(custom=""):
    cands = [custom] if custom else []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env, "")
        cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def kill_pids(pids):
    for pid in pids:
        if not pid:
            continue
        if IS_WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass


def kill_host_browser():
    """Fecha qualquer Chrome/Edge do perfil dedicado do Vortex (nunca o seu navegador normal)."""
    if IS_WIN:
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*VortexHost*browser*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def run_elevated(path, args):
    """Abre como administrador (jogos que exigem elevação). Retorna o PID."""
    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    sei = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x00000040, lpVerb="runas",
                            lpFile=path, lpParameters=args or None, lpDirectory=os.path.dirname(path), nShow=1)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise OSError("O Windows recusou abrir o jogo como administrador (UAC cancelado?)")
    kernel32 = ctypes.windll.kernel32
    kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
    pid = kernel32.GetProcessId(sei.hProcess) if sei.hProcess else 0
    if sei.hProcess:
        kernel32.CloseHandle(sei.hProcess)
    return pid


def spawn(path, args, status):
    try:
        return subprocess.Popen([path] + (args.split() if args else []), cwd=os.path.dirname(path)).pid
    except OSError as e:
        if not (IS_WIN and getattr(e, "winerror", 0) == 740):
            raise
        status("launching", "O jogo exige administrador: confirme o aviso do Windows no PC (ou rode o agente como administrador).")
        return run_elevated(path, args)


class Session:
    """Abre o executável do jogo, coloca em tela cheia/primeiro plano e (modo site) transmite."""

    def __init__(self):
        self.lock = threading.Lock()
        self.game_id = None
        self.title = ""
        self.hwnd = None
        self.pids = set()
        self.before = set()
        self.quit_evt = threading.Event()
        self.timer = None
        self.last_focus = 0.0

    @property
    def busy(self):
        return self.game_id is not None

    def start(self, m, cfg, status, stream):
        with self.lock:
            if self.busy:
                if self.game_id == m["game_id"]:
                    self.cancel_quit()
                    if self.hwnd:
                        focus(self.hwnd)
                    return status("running", f"{self.title} já está aberto no PC.")
                return status("error", "Outro jogo já está aberto no PC. Feche-o primeiro.")
            self.game_id, self.title = m["game_id"], m.get("title", "Jogo")
            self.hwnd, self.pids = None, set()
            self.quit_evt.clear()
        threading.Thread(target=self._guard, args=(m, cfg, status, stream), daemon=True).start()

    def quit(self):
        if self.busy:
            self.quit_evt.set()

    def quit_later(self, secs):
        self.cancel_quit()
        if self.busy:
            self.timer = threading.Timer(secs, self.quit)
            self.timer.daemon = True
            self.timer.start()

    def cancel_quit(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def _guard(self, m, cfg, status, stream):
        try:
            self._run(m, cfg, status, stream)
        except Exception as e:
            status("error", f"Erro no PC: {e}")
        finally:
            self.cancel_quit()
            if stream:
                kill_host_browser()
            self.game_id, self.hwnd, self.pids = None, None, set()

    def _candidates(self):
        return [w for w in list_windows() if w[0] not in self.before and w[2] >= 640 and w[3] >= 360
                and not any(t in w[1].lower() for t in IGNORE_TITLES)]

    def _adopt(self, hwnd, cfg):
        self.hwnd = hwnd
        self.pids.add(window_pid(hwnd))
        if cfg["fullscreen"]:
            make_fullscreen(hwnd)
        focus(hwnd)

    def _run(self, m, cfg, status, stream):
        title, path, args = self.title, m["path"], m.get("args", "")
        if not path.lower().endswith(LAUNCH_EXT):
            return status("error", f"Informe o executável do jogo (.exe), não a pasta: {path}")
        if not os.path.isfile(path):
            return status("error", f"Executável não encontrado no PC: {path}")
        self.before = {w[0] for w in list_windows()}
        status("launching", f"Abrindo {title} no PC…")
        if IS_WIN and path.lower().endswith((".lnk", ".url")):
            os.startfile(path)
        else:
            self.pids.add(spawn(path, args, status))

        deadline = time.time() + cfg["wait"]
        while time.time() < deadline and not self.hwnd and not self.quit_evt.is_set():
            time.sleep(1.5)
            new = self._candidates()
            if new:
                self._adopt(max(new, key=lambda w: w[2] * w[3])[0], cfg)
        if not self.hwnd:
            kill_pids(self.pids)
            return status("error", "A janela do jogo não apareceu. Confira o caminho do .exe.")

        status("launching", "Jogo aberto em tela cheia, aguardando carregar…")
        time.sleep(4)
        if stream:
            if not find_browser(cfg["browser"]):
                kill_pids(self.pids)
                return status("error", "Chrome ou Edge não encontrado no PC.")
            status("capturing", "Iniciando transmissão só da janela do jogo…" if cfg["capture"] == "janela" else "Iniciando transmissão…")
            self._start_browser(m, cfg)
        status("running", f"{title} rodando em tela cheia no PC.")

        gone = 0
        while not self.quit_evt.wait(2):
            alive = window_alive(self.hwnd)
            new = self._candidates()
            best = max(new, key=lambda w: w[2] * w[3]) if new else None
            if best and best[0] != self.hwnd and (not alive or best[2] * best[3] > 1.2 * self._area()):
                self._adopt(best[0], cfg)  # launcher -> janela real do jogo
                alive = True
                if stream and cfg["capture"] == "janela":
                    status("capturing", "Trocando a transmissão para a janela do jogo…")
                    self._start_browser(m, cfg)
            gone = 0 if alive else gone + 2
            if gone >= 20:
                break
        if self.quit_evt.is_set():
            kill_pids(self.pids)
        status("ended", f"{title} foi fechado no PC.")

    def _start_browser(self, m, cfg):
        """Chrome dedicado que captura SÓ a janela do jogo (fica presa nela mesmo trocando de janela no PC)."""
        kill_host_browser()
        source = "Entire screen" if cfg["capture"] == "tela" else (window_title(self.hwnd) or self.title)
        q = urlencode({"token": cfg["token"], "game": m["game_id"], "pin": cfg["pin"],
                       "audio": cfg["audio"], "mode": cfg["capture"]})
        subprocess.Popen([
            find_browser(cfg["browser"]), f"--user-data-dir={PROFILE}", f"--app={cfg['site']}/host-auto?{q}",
            "--lang=en-US", f"--auto-select-desktop-capture-source={source}", "--use-fake-ui-for-media-stream",
            "--autoplay-policy=no-user-gesture-required", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "--no-first-run", "--no-default-browser-check", "--window-size=420,300", "--window-position=0,0",
        ])
        for _ in range(5):  # garante o jogo na frente da janelinha do Chrome
            time.sleep(2)
            if window_alive(self.hwnd):
                focus(self.hwnd)

    def keep_focus(self):
        """Controles do celular sempre vão para o jogo, mesmo se alguém trocar de janela no PC."""
        now = time.time()
        if not IS_WIN or not window_alive(self.hwnd) or now - self.last_focus < 1:
            return
        self.last_focus = now
        if user32.GetForegroundWindow() != self.hwnd:
            focus(self.hwnd)

    def _area(self):
        w = next((w for w in list_windows() if w[0] == self.hwnd), None)
        return w[2] * w[3] if w else 0


session = Session()


# ---------------------------------------------------------------- Sunshine
import base64
import ssl
import urllib.error
import urllib.request
from pathlib import Path

COVERS = Path(__file__).with_name("covers")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 VortexAgent/1.1"
_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", UA)]
urllib.request.install_opener(_opener)  # o proxy do site bloqueia o User-Agent padrão "Python-urllib"


def _sunshine(cfg, method, path, body=None):
    req = urllib.request.Request(cfg["url"].rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    tok = base64.b64encode(f"{cfg['user']}:{cfg['password']}".encode()).decode()
    req.add_header("Authorization", f"Basic {tok}")
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def _cover_png(name, url):
    if not url:
        return ""
    try:
        from PIL import Image
        COVERS.mkdir(exist_ok=True)
        jpg = COVERS / "tmp.img"
        urllib.request.urlretrieve(url, jpg)
        png = COVERS / ("".join(c for c in name if c.isalnum()) + ".png")
        Image.open(jpg).convert("RGB").save(png)
        return str(png)
    except Exception as e:
        print(f"[capa] {name}: {e}")
        return ""


def sunshine_sync(apps, cfg):
    if not cfg.get("user"):
        return {"t": "sunshine-result", "ok": False, "error": "Preencha SUNSHINE_USER e SUNSHINE_PASS no iniciar_agente.bat"}
    try:
        current = _sunshine(cfg, "GET", "/api/apps").get("apps", [])
        names = {a.get("name"): i for i, a in enumerate(current)}
        added = updated = 0
        for app in apps:
            idx = names.get(app["name"], -1)
            body = {"name": app["name"], "output": "", "cmd": app["cmd"], "working-dir": app.get("working-dir", ""),
                    "index": idx, "exclude-global-prep-cmd": False, "elevated": False, "auto-detach": True,
                    "wait-all": True, "exit-timeout": 5, "prep-cmd": [], "detached": [],
                    "image-path": _cover_png(app["name"], app.get("cover"))}
            _sunshine(cfg, "POST", "/api/apps", body)
            if idx < 0:
                added += 1
            else:
                updated += 1
        return {"t": "sunshine-result", "ok": True, "added": added, "updated": updated}
    except Exception as e:
        return {"t": "sunshine-result", "ok": False, "error": f"Sunshine: {e}"}


# ---------------------------------------------------------------- servidor local
def handle(msg):
    t = msg.get("t")
    if t in ("k", "mm", "ma", "mb", "mw", "gp") and session.busy:
        session.keep_focus()
    if t == "k":
        key(msg["code"], msg["down"])
    elif t == "mm":
        mouse_move(msg["dx"], msg["dy"])
    elif t == "ma":
        mouse_abs(msg["x"], msg["y"])
    elif t == "mb":
        mouse_button(msg["b"], msg["down"])
    elif t == "mw":
        mouse_wheel(msg["dy"])
    elif t == "gp":
        gamepad(msg.get("slot", 0), msg["b"], msg["axes"], msg.get("lt", 0), msg.get("rt", 0))
    elif t == "release":
        for p in pads.values():
            p.reset()
            p.update()


def session_msg(t, m, cfg, status, stream):
    """Mensagens de ciclo de vida do jogo (iguais no modo site e no modo Host do PC)."""
    if t == "launch":
        session.start(m, cfg, status, stream)
    elif t == "quit":
        session.quit()
    elif t == "viewers-empty":
        session.quit_later(cfg["grace"])
    elif t == "viewer-joined":
        session.cancel_quit()


def cloud_login(site, email, password):
    req = urllib.request.Request(site.rstrip("/") + "/api/auth/login", method="POST",
                                 data=json.dumps({"email": email, "password": password}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["token"]


async def cloud(cfg):
    """Mantém o PC 'online' no site e abre jogos sob demanda."""
    from urllib.parse import quote
    loop = asyncio.get_running_loop()
    while True:
        try:
            cfg["token"] = await asyncio.to_thread(cloud_login, cfg["site"], cfg["email"], cfg["password"])
            url = cfg["site"].replace("http", "ws", 1).rstrip("/") + f"/api/ws/stream?role=agent&token={quote(cfg['token'])}"
            async with websockets.connect(url, ping_interval=20, user_agent_header=UA) as ws:
                print("[ok] conectado ao site: o PC aparece ONLINE para os jogadores")

                def status(state, text):
                    print(f"[sessão] {text}")
                    asyncio.run_coroutine_threadsafe(ws.send(json.dumps({"type": "status", "state": state, "text": text})), loop)

                async for raw in ws:
                    m = json.loads(raw)
                    session_msg(m.get("type"), m, cfg, status, True)
        except urllib.error.HTTPError as e:
            hint = " (e-mail/senha do site errados no .bat)" if e.code == 401 else ""
            print(f"[site] login falhou: HTTP {e.code}{hint}. Tentando de novo em 5 s…")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[site] desconectado ({e}). Tentando de novo em 5 s…")
            await asyncio.sleep(5)


async def main():
    ap = argparse.ArgumentParser(description="Vortex Host Agent")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--sunshine-url", default="https://localhost:47990")
    ap.add_argument("--sunshine-user", default=os.environ.get("SUNSHINE_USER", ""))
    ap.add_argument("--sunshine-pass", default=os.environ.get("SUNSHINE_PASS", ""))
    ap.add_argument("--site", default=os.environ.get("VORTEX_SITE", ""), help="Endereço do site Vortex")
    ap.add_argument("--email", default=os.environ.get("VORTEX_EMAIL", ""))
    ap.add_argument("--password", default=os.environ.get("VORTEX_PASS", ""))
    ap.add_argument("--capture", default=os.environ.get("VORTEX_CAPTURA") or "janela", choices=["janela", "tela"])
    ap.add_argument("--audio", default=os.environ.get("VORTEX_AUDIO", ""), help="Dispositivo de áudio (ex.: Mixagem estéreo)")
    ap.add_argument("--browser", default=os.environ.get("VORTEX_BROWSER", ""))
    ap.add_argument("--wait", type=int, default=120, help="Segundos esperando a janela do jogo")
    ap.add_argument("--grace", type=int, default=int(os.environ.get("VORTEX_FECHAR_APOS") or 60),
                    help="Segundos sem jogadores até fechar o jogo")
    ap.add_argument("--no-fullscreen", action="store_true", help="Não forçar tela cheia sem bordas")
    ap.add_argument("--pin", default=os.environ.get("VORTEX_PIN") or f"{secrets.randbelow(10**6):06d}")
    a = ap.parse_args()
    sun = {"url": a.sunshine_url, "user": a.sunshine_user, "password": a.sunshine_pass}
    cfg = {"site": a.site.rstrip("/"), "email": a.email, "password": a.password, "capture": a.capture,
           "audio": a.audio, "browser": a.browser, "wait": a.wait, "pin": a.pin, "grace": a.grace,
           "fullscreen": not a.no_fullscreen, "token": ""}

    fails = {"n": 0, "until": 0.0}

    async def serve(ws):
        loop = asyncio.get_running_loop()
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if loop.time() < fails["until"] or hello.get("pin") != a.pin:
                fails["n"] += 1
                if fails["n"] >= 5:
                    fails["n"], fails["until"] = 0, loop.time() + 60
                await ws.send(json.dumps({"t": "auth", "ok": False}))
                return
            fails["n"] = 0
            await ws.send(json.dumps({"t": "auth", "ok": True, "gamepad": vg is not None,
                                      "platform": sys.platform, "sunshine": bool(a.sunshine_user)}))
            print("[ok] navegador host conectado")

            def status(state, text):
                print(f"[sessão] {text}")
                asyncio.run_coroutine_threadsafe(ws.send(json.dumps({"t": "status", "state": state, "text": text})), loop)

            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("t")
                if t == "sunshine-sync":
                    await ws.send(json.dumps(await asyncio.to_thread(sunshine_sync, msg.get("apps", []), sun)))
                elif t in ("launch", "quit", "viewers-empty", "viewer-joined"):
                    session_msg(t, msg, cfg, status, False)
                else:
                    handle(msg)
        except websockets.ConnectionClosed:
            print("[info] a aba do navegador (Host do PC) se desconectou do agente — normal ao fechar, recarregar ou parear de novo. O PC continua ONLINE no site.")
        except Exception as e:
            print(f"[conexão local encerrada] {e}")
        finally:
            handle({"t": "release"})

    print("=" * 52)
    print(f"  Vortex Host Agent  ·  ws://127.0.0.1:{a.port}")
    print(f"  PIN de pareamento: {a.pin}")
    print(f"  Sunshine: {'configurado' if a.sunshine_user else 'não configurado'} ({a.sunshine_url})")
    print(f"  Controle Xbox virtual: {'ATIVO' if vg else 'indisponível'}")
    print(f"  Tela cheia forçada: {'sim' if cfg['fullscreen'] else 'não'}  ·  fecha o jogo {a.grace}s sem jogadores")
    print("=" * 52)
    print(f"  Site: {a.site or '(não configurado: modo manual)'}  ·  captura: {a.capture}")
    async with websockets.serve(serve, "127.0.0.1", a.port, max_size=2**16):
        if a.site and a.email:
            await cloud(cfg)
        else:
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
