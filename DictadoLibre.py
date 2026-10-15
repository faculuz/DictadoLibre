# Dictado Libre - dictado por voz gratuito para Windows (local u online con Groq)
import os, sys, json, time, threading, tempfile, re, io, wave, math, ctypes
from datetime import datetime, timedelta
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
import requests
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRectF, QUrl, QPoint
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QFont, QFontDatabase, QAction,
    QDesktopServices, QGuiApplication,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, QStackedWidget, QSystemTrayIcon, QMenu,
    QMessageBox, QScrollArea,
)

APP = "Dictado Libre"
VERSION = "1.1.0"
REPO = "faculuz/DictadoLibre"
AUMID = "FacundoLuzardo.DictadoLibre"
DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DictadoLibre")
os.makedirs(DIR, exist_ok=True)
CFG = os.path.join(DIR, "config.json")
LOG = os.path.join(DIR, "registro.txt")
HIST = os.path.join(DIR, "historial.json")
STATS = os.path.join(DIR, "metricas.json")
FS = 16000
TYPING_WPM = 40
BAR_N = 24
DEFAULT = {
    "modo": "local", "groq_key": "", "pulir": True, "atajo": "ctrl+alt+space",
    "modo_tecla": "mantener", "estilo": "mantener", "modelo": "small", "idioma": "es",
    "sonidos": True, "inicio_windows": False, "primera_vez": True, "microfono": "",
}
MODELS = [
    ("base", "Rápida"),
    ("small", "Recomendada"),
    ("medium", "Mejor"),
    ("large-v3-turbo", "Máxima"),
]
MODEL_HINT = {
    "base": "Liviana, unos 150 MB. Responde rápido en cualquier computadora.",
    "small": "La que recomendamos. Unos 480 MB y buena precisión.",
    "medium": "Más precisa. Pesa cerca de 1,5 GB y tarda más la primera vez.",
    "large-v3-turbo": "La más precisa. Pesa cerca de 1,6 GB.",
}
STYLES = [("mantener", "Como lo dije"), ("formal", "Formal"), ("mensaje", "Mensaje de chat")]
LANGS = [("es", "Español"), ("en", "Inglés"), ("pt", "Portugués")]
ESTILOS = {
    "mantener": "",
    "formal": " Usa un tono formal y profesional.",
    "mensaje": " Es un mensaje de chat: breve, natural y cercano.",
}
PRETTY_KEY = {
    "space": "Espacio", "enter": "Enter", "tab": "Tab", "esc": "Esc", "backspace": "Retroceso",
    "up": "Arriba", "down": "Abajo", "left": "Izquierda", "right": "Derecha",
    "ctrl": "Ctrl", "alt": "Alt", "shift": "Mayús", "windows": "Windows",
}

def log(*a):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(map(str, a)) + "\n")
    except Exception:
        pass

def _read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load():
    raw = _read_json(CFG, {})
    if not isinstance(raw, dict):
        raw = {}
    c = dict(DEFAULT)
    c.update(raw)
    c["_from_old"] = os.path.exists(CFG) and "microfono" not in raw and not c.get("primera_vez", True)
    return c

cfg = load()
_store_lock = threading.Lock()

def save():
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    _write_json(CFG, data)

def beep(kind):
    if not cfg.get("sonidos", True):
        return
    try:
        import winsound
        f = {"start": (880, 80), "stop": (600, 80), "err": (300, 250)}[kind]
        threading.Thread(target=winsound.Beep, args=f, daemon=True).start()
    except Exception:
        pass

def words_in(text):
    return len(re.findall(r"\S+", text or ""))

def wpm_of(words, seconds):
    if not seconds or seconds < 0.2 or not words:
        return 0
    return int(round(words / (seconds / 60.0)))

def time_saved(words, seconds):
    return max(0.0, (words / TYPING_WPM) * 60.0 - float(seconds or 0))

def fmt_int(n):
    return f"{int(n):,}".replace(",", ".")

def fmt_span(seconds):
    seconds = max(0, int(round(seconds or 0)))
    if seconds < 90:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h" if minutes == 0 else f"{hours} h {minutes} min"

def fmt_when(ts):
    dt = datetime.fromtimestamp(ts)
    today = datetime.now().date()
    if dt.date() == today:
        return "Hoy " + dt.strftime("%H:%M")
    if dt.date() == today - timedelta(days=1):
        return "Ayer " + dt.strftime("%H:%M")
    return dt.strftime("%d/%m/%Y %H:%M")

def pretty_hotkey(h):
    parts = [p.strip() for p in (h or "").split("+") if p.strip()]
    if not parts:
        return "Sin atajo"
    return " + ".join(PRETTY_KEY.get(p, p.upper() if len(p) == 1 else p.capitalize()) for p in parts)

def load_history():
    data = _read_json(HIST, [])
    return data if isinstance(data, list) else []

def load_stats():
    data = _read_json(STATS, {})
    return data if isinstance(data, dict) else {}

def remember(text, seconds):
    w = words_in(text)
    item = {"ts": time.time(), "text": text, "words": w, "seconds": round(float(seconds), 2)}
    with _store_lock:
        hist = load_history()
        hist.insert(0, item)
        del hist[200:]
        _write_json(HIST, hist)
        m = load_stats()
        m["words"] = int(m.get("words", 0)) + w
        m["seconds"] = float(m.get("seconds", 0)) + float(seconds)
        m["sessions"] = int(m.get("sessions", 0)) + 1
        m["last_words"] = w
        m["last_seconds"] = round(float(seconds), 2)
        m["last_wpm"] = wpm_of(w, seconds)
        _write_json(STATS, m)
    if bridge is not None:
        bridge.history_changed.emit()

def delete_history(index):
    with _store_lock:
        hist = load_history()
        if 0 <= index < len(hist):
            hist.pop(index)
            _write_json(HIST, hist)
    if bridge is not None:
        bridge.history_changed.emit()

def clear_history():
    with _store_lock:
        _write_json(HIST, [])
    if bridge is not None:
        bridge.history_changed.emit()

# ---------- motores ----------
_model = None
_model_lock = threading.Lock()
state_name = "listo"
bridge = None
controller = None
recording = False
frames = []
stream = None
abort = threading.Event()
hk = None
capturing = False
mic_lock = threading.RLock()
level_lock = threading.Lock()
levels = [0.08] * BAR_N
update = {"ver": None, "url": None}
paste_lock = threading.Lock()

def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

def set_state(s, tip=""):
    global state_name
    if s == "listo" and tip == "" and state_name in ("grabando", "procesando"):
        return
    state_name = s
    if bridge is not None:
        bridge.state_changed.emit(s, tip or "")

def notify(msg):
    if bridge is not None:
        bridge.notice.emit(str(msg))

def human_error(e):
    raw = str(e).lower()
    if "401" in raw or "unauthorized" in raw or ("invalid" in raw and "key" in raw):
        return "La clave de Groq fue rechazada. Abrí Configuración y pegalá de nuevo."
    if "timeout" in raw or "timed out" in raw:
        return "Tardó demasiado. Probá otra vez."
    if "microphone" in raw or "input device" in raw or "invalid device" in raw:
        return "No pude usar el micrófono. Elegí otro en Configuración."
    if "connection" in raw or "name resolution" in raw or "failed to establish" in raw:
        return "Sin internet. Podés dictar con el modo de esta computadora."
    return "No se pudo dictar. El detalle está en el registro de errores."

def local_model():
    global _model
    with _model_lock:
        if _model is None:
            if state_name not in ("grabando", "procesando"):
                set_state("cargando", "")
            from faster_whisper import WhisperModel
            _model = WhisperModel(cfg["modelo"], device="cpu", compute_type="int8",
                                  download_root=os.path.join(DIR, "modelos"))
            if state_name == "cargando":
                set_state("listo", "")
        return _model

def transcribe_local(audio):
    segs, _ = local_model().transcribe(
        audio.astype(np.float32) / 32768.0, language=cfg["idioma"] or None,
        beam_size=5, vad_filter=True,
        initial_prompt="Hola, ¿cómo estás? Esto es un dictado en español, con puntuación correcta.")
    return " ".join(s.text.strip() for s in segs).strip()

def wav_bytes(audio):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(audio.tobytes())
    return b.getvalue()

def transcribe_groq(audio):
    r = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": "Bearer " + cfg["groq_key"].strip()},
        files={"file": ("a.wav", wav_bytes(audio), "audio/wav")},
        data={"model": "whisper-large-v3-turbo", "language": cfg["idioma"], "response_format": "json"},
        timeout=30)
    r.raise_for_status()
    return r.json()["text"].strip()

def polish_groq(text):
    prompt = (
        "Eres un editor de dictado. Recibes texto transcrito por voz en español. Corrige puntuación, mayúsculas y ortografía, "
        "elimina muletillas (eh, este, o sea, mmm), repeticiones y autocorrecciones (si la persona dice 'no, perdón' conserva solo lo corregido). "
        "Si dicta 'punto y aparte' o 'nueva línea' inserta salto de línea. Respeta palabras en inglés. NO respondas preguntas ni agregues nada: "
        "devuelve SOLO el texto final." + ESTILOS.get(cfg["estilo"], ""))
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + cfg["groq_key"].strip()},
        json={"model": "llama-3.3-70b-versatile", "temperature": 0,
              "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}]},
        timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def polish_local(t):
    t = re.sub(r"\b(eh+|em+|mm+|este\.\.\.|ehm)\b[,.]?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*(punto y aparte|nueva l[ií]nea)\s*[.,]?\s*", ".\n", t, flags=re.I)
    t = re.sub(r"\b(\w+)( \1\b)+", r"\1", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t[:1].upper() + t[1:] if t else t

def process(audio):
    try:
        if abort.is_set():
            return
        if len(audio) < FS * 0.3:
            set_state("listo", "corto")
            return
        set_state("procesando", "")
        text = ""
        online = cfg["modo"] == "online" and cfg["groq_key"].strip()
        if online:
            try:
                text = transcribe_groq(audio)
                if cfg["pulir"] and text:
                    try:
                        text = polish_groq(text)
                    except Exception as e:
                        log("pulido falló", e)
                        text = polish_local(text)
            except Exception as e:
                log("Groq falló, uso local:", e)
                text = polish_local(transcribe_local(audio))
        else:
            text = transcribe_local(audio)
            if cfg["pulir"]:
                text = polish_local(text)
        if abort.is_set():
            return
        if text:
            paste(text)
            try:
                remember(text, len(audio) / FS)
            except Exception as e:
                log("historial", repr(e))
            if not abort.is_set():
                set_state("listo", "listo")
        elif not abort.is_set():
            set_state("listo", "vacio")
    except Exception as e:
        log("error:", repr(e))
        beep("err")
        if not abort.is_set():
            notify(human_error(e))
            set_state("listo", "error")
    finally:
        if controller is not None:
            controller.maybe_monitor()

def paste(text):
    with paste_lock:
        try:
            old = pyperclip.paste()
        except Exception:
            old = None
        pyperclip.copy(text + " ")
        for _ in range(40):
            try:
                if not any(keyboard.is_pressed(k) for k in ("ctrl", "alt", "shift", "windows")):
                    break
            except Exception:
                break
            time.sleep(0.05)
        time.sleep(0.05)
        keyboard.send("ctrl+v")
        time.sleep(0.3)
        if old is not None:
            threading.Timer(0.7, lambda o=old: pyperclip.copy(o)).start()

def push_level(chunk):
    if chunk is None or getattr(chunk, "size", 0) == 0:
        return
    peak = float(np.max(np.abs(chunk))) / 32768.0
    v = min(1.0, peak * 4.5)
    if v < 0.06:
        v = 0.08
    with level_lock:
        prev = levels[-1]
        levels.pop(0)
        levels.append(prev * 0.35 + v * 0.65)

def list_mics():
    try:
        devs = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception as e:
        log("mics", repr(e))
        return []
    wasapi = next((i for i, h in enumerate(hostapis) if "WASAPI" in h["name"].upper()), None)
    items, seen = [], set()

    def add(i, d):
        if d["max_input_channels"] < 1:
            return
        name = str(d["name"]).strip()
        if not name or name in seen:
            return
        seen.add(name)
        items.append((name, i))

    if wasapi is not None:
        for i, d in enumerate(devs):
            if d["hostapi"] == wasapi:
                add(i, d)
    if not items:
        for i, d in enumerate(devs):
            add(i, d)
    return items

def resolve_device(name):
    if not name:
        return None
    for mic_name, idx in list_mics():
        if mic_name == name:
            return idx
    return None

def cb(indata, n, t, status):
    if status:
        log("audio", status)
    if recording:
        frames.append(indata.copy())
        push_level(indata)

def start_rec():
    global recording, frames, stream
    if recording or capturing:
        return
    with mic_lock:
        if recording:
            return
        if controller is not None:
            controller._stop_monitor()
        abort.clear()
        with level_lock:
            for i in range(len(levels)):
                levels[i] = 0.08
        frames = []
        recording = True
        beep("start")
        set_state("grabando", "")
        dev = resolve_device(cfg.get("microfono") or "")
        try:
            try:
                stream = sd.InputStream(samplerate=FS, channels=1, dtype="int16", callback=cb,
                                        device=dev, blocksize=480)
                stream.start()
            except Exception:
                if dev is None:
                    raise
                log("micrófono elegido falló, uso predeterminado")
                stream = sd.InputStream(samplerate=FS, channels=1, dtype="int16", callback=cb, blocksize=480)
                stream.start()
                notify("Ese micrófono no respondió. Estoy usando el predeterminado.")
        except Exception as e:
            recording = False
            stream = None
            log("micrófono:", repr(e))
            beep("err")
            notify("No encuentro un micrófono. Conectalo o elegí otro en Configuración.")
            set_state("listo", "error")

def stop_rec():
    global recording, stream
    with mic_lock:
        if not recording:
            return
        recording = False
        if not abort.is_set():
            beep("stop")
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception:
            pass
        stream = None
        audio = np.concatenate(frames).flatten() if frames else np.zeros(0, np.int16)
    if abort.is_set():
        set_state("listo", "cancelado")
        if controller is not None:
            controller.maybe_monitor()
        return
    threading.Thread(target=process, args=(audio,), daemon=True).start()

def cancel_dictation():
    abort.set()
    if recording:
        stop_rec()
    elif state_name == "procesando":
        set_state("listo", "cancelado")

def on_hotkey():
    if capturing:
        return
    if cfg.get("modo_tecla") == "alternar":
        stop_rec() if recording else start_rec()
        return
    if recording:
        return
    start_rec()

    def waiter():
        key = cfg.get("atajo") or ""
        last = key.split("+")[-1] if key else ""
        while True:
            try:
                held = (key and keyboard.is_pressed(key)) or (last and keyboard.is_pressed(last))
            except Exception:
                held = False
            if not held:
                break
            time.sleep(0.03)
        stop_rec()

    threading.Thread(target=waiter, daemon=True).start()

def register_hotkey(announce=True):
    global hk
    try:
        if hk:
            keyboard.remove_hotkey(hk)
    except Exception:
        pass
    hk = None
    atajo = (cfg.get("atajo") or "").strip().lower()

    def bind(combo):
        return keyboard.add_hotkey(combo, on_hotkey, suppress=False, trigger_on_release=False)

    try:
        hk = bind(atajo)
        return True
    except Exception as e:
        log("atajo", repr(e))
        if atajo != "ctrl+alt+space":
            cfg["atajo"] = "ctrl+alt+space"
            save()
            try:
                hk = bind(cfg["atajo"])
                if announce:
                    notify("Ese atajo no funciona. Volví a Ctrl + Alt + Espacio.")
                return True
            except Exception as e2:
                log("atajo fallback", repr(e2))
        if announce:
            notify("No pude activar el atajo. Abrí Configuración y elegí otro.")
        return False

# ---------- actualizaciones automáticas ----------
def vtuple(v):
    try:
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    except Exception:
        return (0,)

def check_update(manual=False):
    try:
        r = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest", timeout=15,
            headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        j = r.json()
        tag = j.get("tag_name", "")
        url = next((a["browser_download_url"] for a in j.get("assets", []) if a["name"].lower().endswith("setup.exe")), None)
        if url and vtuple(tag) > vtuple(VERSION):
            update.update(ver=tag.lstrip("v"), url=url)
            if bridge is not None:
                bridge.update_ready.emit()
            notify(f"Hay una versión nueva ({tag}). Clic derecho en el ícono → Instalar actualización.")
        elif manual:
            notify(f"Ya tenés la última versión ({VERSION}).")
    except Exception as e:
        log("update check", e)
        if manual:
            notify("No pude buscar actualizaciones. Revisá tu internet.")

def update_loop():
    time.sleep(10)
    while True:
        check_update()
        time.sleep(24 * 3600)

def install_update():
    try:
        notify(f"Descargando la versión {update['ver']}...")
        set_state("cargando", "actualizando")
        p = os.path.join(tempfile.gettempdir(), "DictadoLibre-Setup.exe")
        with requests.get(update["url"], stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(p, "wb") as f:
                for c in r.iter_content(1 << 20):
                    f.write(c)
        import subprocess
        subprocess.Popen(
            [p, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
            close_fds=True)
        os._exit(0)
    except Exception as e:
        log("update install", e)
        notify("No se pudo actualizar: " + str(e)[:100])
        set_state("listo", "error")

def set_autostart(on):
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if on:
            winreg.SetValueEx(k, "DictadoLibre", 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try:
                winreg.DeleteValue(k, "DictadoLibre")
            except FileNotFoundError:
                pass
        return True
    except Exception as e:
        log("autostart", e)
        return False

# ---------- interfaz ----------
def app_font():
    families = set(QFontDatabase.families())
    for name in ("Segoe UI", "Inter", "Noto Sans"):
        if name in families:
            return QFont(name, 10)
    return QFont("Sans Serif", 10)

def _font(size, weight=QFont.Weight.Normal):
    f = QFont(QApplication.font())
    f.setPixelSize(size)
    f.setWeight(weight)
    return f

def make_tray_icon(state):
    colors = {"listo": "#3dd68c", "grabando": "#ff4d6a", "procesando": "#ffc14d", "cargando": "#8b909e"}
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colors.get(state, "#8b909e")))
    p.drawEllipse(2, 2, 60, 60)
    p.setBrush(QColor("white"))
    p.drawRoundedRect(QRectF(24, 12, 16, 26), 8, 8)
    pen = QPen(QColor("white"), 4, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(16, 20, 32, 26), 180 * 16, 180 * 16)
    p.drawLine(32, 46, 32, 54)
    p.drawLine(22, 54, 42, 54)
    p.end()
    return QIcon(pm)

def brand_pixmap(size=36):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#7c6af7"))
    p.drawEllipse(0, 0, size, size)
    s = size / 64
    p.setBrush(QColor("white"))
    p.drawRoundedRect(QRectF(24 * s, 12 * s, 16 * s, 26 * s), 8 * s, 8 * s)
    pen = QPen(QColor("white"), max(2, 4 * s), Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(16 * s, 20 * s, 32 * s, 26 * s), 180 * 16, 180 * 16)
    p.drawLine(QPoint(int(32 * s), int(46 * s)), QPoint(int(32 * s), int(54 * s)))
    p.drawLine(QPoint(int(22 * s), int(54 * s)), QPoint(int(42 * s), int(54 * s)))
    p.end()
    return pm

APP_QSS = """
QMenu { background: #1b1e27; color: #f4f5f7; border: 1px solid #2a2e3a; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 8px 16px; border-radius: 8px; }
QMenu::item:selected { background: #2c2844; }
QMenu::item:disabled { color: #8b909e; }
QMenu::separator { height: 1px; background: #2a2e3a; margin: 6px 8px; }
QMessageBox { background: #16181f; }
QMessageBox QLabel { color: #f4f5f7; }
QMessageBox QPushButton { background: #7c6af7; color: white; border: none; border-radius: 10px; padding: 8px 16px; min-width: 88px; }
QMessageBox QPushButton:hover { background: #8d7cff; }
"""

SETTINGS_QSS = """
QWidget#settings { background: #0e0f13; color: #f4f5f7; }
QLabel { background: transparent; color: #f4f5f7; }
QLabel#muted { color: #9aa0ad; }
QLabel#h1 { font-size: 26px; font-weight: 600; }
QLabel#hotkey { font-size: 22px; font-weight: 600; }
QLabel#metric { font-size: 30px; font-weight: 700; }
QLabel#brand { font-size: 16px; font-weight: 600; }
QFrame#side { background: #14161c; border-right: 1px solid #232633; }
QFrame#card { background: #1b1e27; border: 1px solid #2a2e3a; border-radius: 16px; }
QFrame#cardOn { background: #221f33; border: 2px solid #7c6af7; border-radius: 16px; }
QFrame#footer { background: #12141a; border-top: 1px solid #232633; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QPushButton { border: none; border-radius: 12px; padding: 8px 14px; background: #252836; color: #f4f5f7; }
QPushButton:hover { background: #313546; }
QPushButton#primary { background: #7c6af7; color: white; font-weight: 600; padding: 10px 18px; }
QPushButton#primary:hover { background: #8d7cff; }
QPushButton#ghost { background: transparent; color: #c8cad3; }
QPushButton#ghost:hover { background: #252836; }
QPushButton#nav { background: transparent; color: #b7bac6; text-align: left; padding: 10px 14px; border-radius: 12px; }
QPushButton#nav:hover { background: #1d202a; color: white; }
QPushButton#nav:checked { background: #2a2740; color: white; font-weight: 600; }
QPushButton#danger { background: #2a2030; color: #ff8b9a; }
QPushButton#danger:hover { background: #3a2230; }
QPushButton#chip { background: #252836; color: #f4f5f7; border-radius: 10px; padding: 6px 12px; }
QLineEdit, QComboBox {
    background: #12141c; color: #f4f5f7; border: 1px solid #343848; border-radius: 12px; padding: 8px 12px; min-height: 22px;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #7c6af7; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox QAbstractItemView { background: #1b1e27; color: #f4f5f7; selection-background-color: #7c6af7; border: 1px solid #343848; }
QScrollBar:vertical { background: #1a1d27; width: 12px; margin: 4px 2px; border-radius: 6px; }
QScrollBar::handle:vertical { background: #5c6174; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }
"""

class Bridge(QObject):
    state_changed = Signal(str, str)
    notice = Signal(str)
    update_ready = Signal()
    history_changed = Signal()
    mic_level = Signal(float)

class Pill(QWidget):
    def __init__(self):
        super().__init__()
        self.state = "listo"
        self.tip = ""
        self._phase = 0.0
        self._token = 0
        self._hover_x = False
        self._cancel = QRectF()
        self.setFixedSize(440, 92)
        self.setWindowTitle(APP)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.availableGeometryChanged.connect(lambda *_: self.place())

    def place(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.x() + (geo.width() - self.width()) // 2, geo.y() + geo.height() - self.height() - 18)

    def _tick(self):
        if self.isVisible():
            self._phase += 0.22
            self.update()

    def on_state(self, state, tip):
        self.state = state
        self.tip = tip or ""
        self._token += 1
        token = self._token
        title, hint = self._copy()
        self.setToolTip(f"{title}. {hint}".strip())
        if state in ("grabando", "procesando", "cargando"):
            self.place()
            self.show()
            self.raise_()
        elif tip in ("listo", "corto", "vacio", "error", "cancelado"):
            self.place()
            self.show()
            self.raise_()
            QTimer.singleShot(1100, lambda t=token: self._hide_if(t))
        else:
            self.hide()
        self.update()

    def _hide_if(self, token):
        if token == self._token and self.state == "listo":
            self.hide()

    def showEvent(self, e):
        super().showEvent(e)
        self.place()
        self._noactivate()

    def _noactivate(self):
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= 0x08000000 | 0x00000080 | 0x00000008  # NOACTIVATE | TOOLWINDOW | TOPMOST
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _copy(self):
        if self.tip == "actualizando":
            return "Actualizando", "Se instala sola"
        if self.state == "grabando":
            if cfg.get("modo_tecla") == "alternar":
                return "Escuchando", "Tocá de nuevo"
            return "Escuchando", "Soltá para pegar"
        if self.state == "procesando":
            return "Procesando", "Un segundo"
        if self.state == "cargando":
            return "Preparando", "Solo la primera vez"
        return {
            "listo": ("Listo", "Ya está escrito"),
            "corto": ("Muy corto", "Hablá un poco más"),
            "vacio": ("No escuché", "Probá otra vez"),
            "error": ("Error", "Revisá el ícono"),
            "cancelado": ("Cancelado", "No escribí nada"),
        }.get(self.tip, ("Listo", ""))

    def _dot(self):
        if self.state == "grabando":
            return QColor("#ff4d6a")
        if self.state == "procesando":
            return QColor("#ffc14d")
        if self.state == "cargando":
            return QColor("#a4a8b5")
        if self.tip == "listo":
            return QColor("#3dd68c")
        if self.tip == "error":
            return QColor("#ff4d6a")
        return QColor("#ffc14d")

    def _bars(self):
        if self.state == "grabando":
            with level_lock:
                data = list(levels)
            return [max(0.08, min(1.0, v)) for v in data]
        if self.state == "procesando":
            return [0.18 + 0.82 * abs(math.sin(self._phase + i * 0.42)) for i in range(BAR_N)]
        if self.state == "cargando":
            return [0.12 + 0.28 * abs(math.sin(self._phase * 0.55 + i * 0.38)) for i in range(BAR_N)]
        return [0.1 + 0.08 * abs(math.sin(i)) for i in range(BAR_N)]

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        outer = QRectF(8, 10, self.width() - 16, self.height() - 22)
        for i, alpha in ((6, 16), (3, 28)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(outer.adjusted(-i, i * 0.3, i, i), 28, 28)
        p.setPen(QPen(QColor(255, 255, 255, 32), 1))
        p.setBrush(QColor(16, 17, 24, 244))
        p.drawRoundedRect(outer, 28, 28)
        dot = self._dot()
        cx, cy = outer.left() + 26, outer.center().y()
        if self.state == "grabando":
            pulse = 6 + 3 * abs(math.sin(self._phase * 1.4))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(dot.red(), dot.green(), dot.blue(), 50))
            p.drawEllipse(QRectF(cx - pulse, cy - pulse, pulse * 2, pulse * 2))
        p.setBrush(dot)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - 5, cy - 5, 10, 10))
        bars = self._bars()
        left = outer.left() + 46
        right = outer.right() - 186
        gap = 3
        bw = max(2.0, (right - left - gap * (len(bars) - 1)) / len(bars))
        max_h = outer.height() - 22
        p.setBrush(QColor("#eeeaff") if self.state == "grabando" else QColor("#c4bdf2"))
        for i, v in enumerate(bars):
            h = max(4.0, max_h * v)
            x = left + i * (bw + gap)
            p.drawRoundedRect(QRectF(x, cy - h / 2, bw, h), 1.6, 1.6)
        title, hint = self._copy()
        text_x = outer.right() - 174
        p.setPen(QColor("#f4f5f7"))
        p.setFont(_font(14, QFont.Weight.DemiBold))
        p.drawText(QRectF(text_x, outer.top() + 14, 128, 20), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.setPen(QColor("#9aa0ad"))
        p.setFont(_font(11))
        p.drawText(QRectF(text_x, outer.top() + 34, 128, 16), Qt.AlignLeft | Qt.AlignVCenter, hint)
        show_x = self.state in ("grabando", "procesando")
        self._cancel = QRectF(outer.right() - 38, cy - 12, 24, 24) if show_x else QRectF()
        if show_x:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 42 if self._hover_x else 16))
            p.drawEllipse(self._cancel)
            p.setPen(QPen(QColor("#f4f5f7"), 1.6, Qt.SolidLine, Qt.RoundCap))
            c = self._cancel.center()
            p.drawLine(QPoint(int(c.x() - 4), int(c.y() - 4)), QPoint(int(c.x() + 4), int(c.y() + 4)))
            p.drawLine(QPoint(int(c.x() + 4), int(c.y() - 4)), QPoint(int(c.x() - 4), int(c.y() + 4)))
        p.end()

    def mouseMoveEvent(self, e):
        hover = self._cancel.contains(e.position())
        if hover != self._hover_x:
            self._hover_x = hover
            self.update()
        self.setCursor(Qt.PointingHandCursor if self.state in ("grabando", "procesando") else Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._cancel.contains(e.position()) and self.state in ("grabando", "procesando"):
            cancel_dictation()
            return
        if self.state == "grabando":
            stop_rec()

class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False):
        super().__init__()
        self._on = bool(checked)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def isChecked(self):
        return self._on

    def setChecked(self, on):
        self._on = bool(on)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on = not self._on
            self.update()
            self.toggled.emit(self._on)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#7c6af7" if self._on else "#343846"))
        p.drawRoundedRect(0, 0, 46, 26, 13, 13)
        p.setBrush(QColor("white"))
        p.drawEllipse(23 if self._on else 3, 3, 20, 20)
        p.end()

class LevelBar(QWidget):
    def __init__(self):
        super().__init__()
        self.level = 0.0
        self.setFixedHeight(12)

    def set_level(self, v):
        self.level = max(0.0, min(1.0, float(v)))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2e3a"))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 6, 6)
        w = self.width() * self.level
        if w > 0:
            p.setBrush(QColor("#7c6af7" if self.level < 0.85 else "#3dd68c"))
            p.drawRoundedRect(QRectF(0, 0, w, self.height()), 6, 6)
        p.end()

def button(text, kind="ghost"):
    b = QPushButton(text)
    b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(38 if kind != "primary" else 42)
    return b

def card():
    f = QFrame()
    f.setObjectName("card")
    f.setAttribute(Qt.WA_StyledBackground, True)
    return f

def muted(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab

def switch_row(title, subtitle, sw):
    row = card()
    h = QHBoxLayout(row)
    h.setContentsMargins(16, 12, 16, 12)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setWordWrap(True)
    s = muted(subtitle)
    col.addWidget(t)
    col.addWidget(s)
    h.addLayout(col, 1)
    h.addWidget(sw, 0, Qt.AlignVCenter)
    return row

class Choice(QFrame):
    def __init__(self, title, subtitle):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        self.title = QLabel(title)
        self.title.setWordWrap(True)
        f = QFont(self.title.font())
        f.setWeight(QFont.Weight.DemiBold)
        self.title.setFont(f)
        self.sub = muted(subtitle)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)

    def set_on(self, on):
        self.setObjectName("cardOn" if on else "card")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked()

    def clicked(self):
        pass

def scroller(inner):
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sc.setWidget(inner)
    sc.viewport().setStyleSheet("background: transparent;")
    return sc

def polish_combo(combo):
    combo.setMinimumHeight(40)
    view = combo.view()
    view.setStyleSheet("background:#1b1e27; color:#f4f5f7; selection-background-color:#7c6af7; selection-color:white; padding:4px;")

def fill_combo(combo, pairs, current):
    combo.clear()
    for value, label in pairs:
        combo.addItem(label, value)
    if current and combo.findData(current) < 0:
        combo.addItem(str(current), current)
    i = combo.findData(current)
    combo.setCurrentIndex(i if i >= 0 else 0)

class Settings(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("settings")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(APP)
        self.setStyleSheet(SETTINGS_QSS)
        self.setMinimumSize(880, 620)
        self.resize(980, 680)
        self.hotkey = cfg.get("atajo") or "ctrl+alt+space"
        self.modo = cfg.get("modo") or "local"
        self.tecla = cfg.get("modo_tecla") or "mantener"
        self._capturing = False
        ico = resource("icon.ico")
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))
        else:
            self.setWindowIcon(make_tray_icon("listo"))
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.addWidget(scroller(self._page_general()))
        self.stack.addWidget(scroller(self._page_voz()))
        self.stack.addWidget(scroller(self._page_mic()))
        self.stack.addWidget(scroller(self._page_hist()))
        self.stack.addWidget(scroller(self._page_stats()))
        right.addWidget(self.stack, 1)
        self.footer = self._footer()
        right.addWidget(self.footer)
        wrap = QWidget()
        wrap.setLayout(right)
        root.addWidget(wrap, 1)
        self.stack.currentChanged.connect(self._on_page)
        self._select_nav(0)
        if bridge is not None:
            bridge.history_changed.connect(self._refresh_lists)
            bridge.update_ready.connect(self._refresh_update)
            bridge.mic_level.connect(self.level.set_level)

    def _sidebar(self):
        side = QFrame()
        side.setObjectName("side")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(236)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(brand_pixmap(34))
        logo.setFixedSize(34, 34)
        name = QLabel(APP)
        name.setObjectName("brand")
        brand.addWidget(logo)
        brand.addWidget(name)
        brand.addStretch(1)
        lay.addLayout(brand)
        ver = muted(f"Versión {VERSION}")
        lay.addWidget(ver)
        lay.addSpacing(18)
        self.nav = []
        for i, text in enumerate(("General", "Voz", "Micrófono", "Historial", "Métricas")):
            b = button(text, "nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=i: self.open_page(n))
            self.nav.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        self.update_btn = button("Buscar actualizaciones", "ghost")
        self.update_btn.clicked.connect(self._update_click)
        lay.addWidget(self.update_btn)
        self.update_hint = muted("Estás al día.")
        lay.addWidget(self.update_hint)
        return side

    def _footer(self):
        bar = QFrame()
        bar.setObjectName("footer")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(28, 12, 28, 12)
        self.footer_msg = muted("El atajo, la voz y el micrófono se aplican al guardar.")
        h.addWidget(self.footer_msg, 1)
        self.save_btn = button("Guardar", "primary")
        self.save_btn.setFixedWidth(140)
        self.save_btn.clicked.connect(self._save)
        h.addWidget(self.save_btn)
        return bar

    def _page_shell(self, title, subtitle):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 18)
        lay.setSpacing(12)
        h = QLabel(title)
        h.setObjectName("h1")
        lay.addWidget(h)
        lay.addWidget(muted(subtitle))
        lay.addSpacing(6)
        return page, lay

    def _page_general(self):
        page, lay = self._page_shell("General", "Cómo querés dictar. Mantené el atajo mientras hablás, o usá un toque.")
        box = card()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.setSpacing(8)
        k = QLabel("Atajo")
        k.setObjectName("muted")
        self.hk_label = QLabel(pretty_hotkey(self.hotkey))
        self.hk_label.setObjectName("hotkey")
        self.hk_btn = button("Cambiar atajo", "ghost")
        self.hk_btn.clicked.connect(self._begin_capture)
        bl.addWidget(k)
        bl.addWidget(self.hk_label)
        bl.addWidget(self.hk_btn, 0, Qt.AlignLeft)
        bl.addWidget(muted("Apretá Cambiar atajo y después la combinación. Por ejemplo, Ctrl + Alt + Espacio."))
        lay.addWidget(box)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.card_hold = Choice("Mantener apretado", "Hablás con la tecla abajo. Al soltar, el texto se escribe donde está el cursor.")
        self.card_toggle = Choice("Un toque", "Un toque empieza y otro termina. Sirve para dictados largos.")
        self.card_hold.clicked = lambda: self._set_tecla("mantener")
        self.card_toggle.clicked = lambda: self._set_tecla("alternar")
        row.addWidget(self.card_hold, 1)
        row.addWidget(self.card_toggle, 1)
        lay.addLayout(row)
        self._set_tecla(self.tecla)
        self.sw_son = Switch(cfg.get("sonidos", True))
        self.sw_ini = Switch(cfg.get("inicio_windows", False))
        lay.addWidget(switch_row("Sonido", "Un tono corto al empezar y al soltar.", self.sw_son))
        lay.addWidget(switch_row("Abrir con Windows", "Dictado Libre queda listo junto al reloj cuando prendés la computadora.", self.sw_ini))
        lay.addStretch(1)
        return page

    def _page_voz(self):
        page, lay = self._page_shell("Voz", "Elegí si el dictado se hace en esta computadora o por internet.")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.card_local = Choice("En esta computadora", "Privado, sin internet. La primera vez se descarga la voz.")
        self.card_online = Choice("Por internet, con Groq", "Más rápido y preciso. Hace falta una clave gratis.")
        self.card_local.clicked = lambda: self._set_modo("local")
        self.card_online.clicked = lambda: self._set_modo("online")
        row.addWidget(self.card_local, 1)
        row.addWidget(self.card_online, 1)
        lay.addLayout(row)
        self._set_modo(self.modo)
        box = card()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.setSpacing(8)
        bl.addWidget(QLabel("Clave de Groq"))
        self.key = QLineEdit(cfg.get("groq_key", ""))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Pegá acá la clave")
        bl.addWidget(self.key)
        tools = QHBoxLayout()
        link = button("Conseguir la clave gratis", "ghost")
        link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://console.groq.com/keys")))
        self.sw_show = Switch(False)
        self.sw_show.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        show_row = QHBoxLayout()
        show_row.addWidget(muted("Mostrar clave"))
        show_row.addWidget(self.sw_show)
        tools.addWidget(link, 0, Qt.AlignLeft)
        tools.addStretch(1)
        tools.addLayout(show_row)
        bl.addLayout(tools)
        bl.addWidget(muted("Groq te da una clave gratis. Sin ella, el dictado sigue funcionando en esta computadora."))
        lay.addWidget(box)
        box2 = card()
        b2 = QVBoxLayout(box2)
        b2.setContentsMargins(18, 14, 18, 14)
        b2.setSpacing(8)
        cols = QHBoxLayout()
        cols.setSpacing(16)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(6)
        right.setSpacing(6)
        left.addWidget(QLabel("Calidad en esta computadora"))
        self.model = QComboBox()
        polish_combo(self.model)
        fill_combo(self.model, MODELS, cfg.get("modelo") or "small")
        self.model.currentIndexChanged.connect(self._model_hint)
        left.addWidget(self.model)
        right.addWidget(QLabel("Idioma"))
        self.lang = QComboBox()
        polish_combo(self.lang)
        fill_combo(self.lang, LANGS, cfg.get("idioma") or "es")
        right.addWidget(self.lang)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        b2.addLayout(cols)
        self.model_hint = muted(MODEL_HINT.get(cfg.get("modelo") or "small", ""))
        b2.addWidget(self.model_hint)
        lay.addWidget(box2)
        box3 = card()
        b3 = QVBoxLayout(box3)
        b3.setContentsMargins(16, 12, 16, 14)
        b3.setSpacing(8)
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(QLabel("Pulir el texto"))
        col.addWidget(muted("Saca muletillas, acomoda puntos y mayúsculas. No cambia lo que quisiste decir."))
        self.sw_pulir = Switch(cfg.get("pulir", True))
        top.addLayout(col, 1)
        top.addWidget(self.sw_pulir, 0, Qt.AlignVCenter)
        b3.addLayout(top)
        b3.addWidget(QLabel("Estilo, cuando pulís por internet"))
        self.style = QComboBox()
        polish_combo(self.style)
        fill_combo(self.style, STYLES, cfg.get("estilo") or "mantener")
        b3.addWidget(self.style)
        b3.addWidget(muted("Formal queda más profesional. Mensaje de chat, más corto y cercano."))
        lay.addWidget(box3)
        lay.addStretch(1)
        return page

    def _page_mic(self):
        page, lay = self._page_shell("Micrófono", "Elegí con cuál querés dictar. La barra se mueve si te escucha.")
        box = card()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.setSpacing(10)
        self.mic = QComboBox()
        polish_combo(self.mic)
        self._fill_mics()
        bl.addWidget(self.mic)
        ref = button("Actualizar lista", "ghost")
        ref.clicked.connect(self._fill_mics)
        bl.addWidget(ref, 0, Qt.AlignLeft)
        self.level = LevelBar()
        bl.addWidget(self.level)
        self.mic_msg = muted("Hablá ahora. Si la barra se mueve, ese micrófono sirve. Después tocá Guardar.")
        bl.addWidget(self.mic_msg)
        lay.addWidget(box)
        lay.addStretch(1)
        self.mic.currentIndexChanged.connect(lambda *_: self._mic_changed())
        return page

    def _page_hist(self):
        page, lay = self._page_shell("Historial", "Lo que dictaste queda guardado solo en esta computadora.")
        top = QHBoxLayout()
        top.addStretch(1)
        wipe = button("Borrar historial", "danger")
        wipe.clicked.connect(self._wipe_history)
        top.addWidget(wipe)
        lay.addLayout(top)
        self.hist_box = QVBoxLayout()
        self.hist_box.setSpacing(10)
        lay.addLayout(self.hist_box)
        lay.addStretch(1)
        self._refresh_history()
        return page

    def _page_stats(self):
        page, lay = self._page_shell("Tus números", "Un vistazo de lo que venís dictando.")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.m_words, self.m_words_n = self._metric("0", "Palabras dictadas")
        self.m_wpm, self.m_wpm_n = self._metric("0", "Palabras por minuto")
        self.m_saved, self.m_saved_n = self._metric("0 s", "Tiempo ahorrado")
        row.addWidget(self.m_words, 1)
        row.addWidget(self.m_wpm, 1)
        row.addWidget(self.m_saved, 1)
        lay.addLayout(row)
        self.last_card = card()
        ll = QVBoxLayout(self.last_card)
        ll.setContentsMargins(18, 16, 18, 16)
        self.last_label = QLabel("Todavía no hay dictados.")
        self.last_label.setWordWrap(True)
        ll.addWidget(self.last_label)
        lay.addWidget(self.last_card)
        lay.addWidget(muted(
            "El tiempo ahorrado compara tu dictado con escribir a 40 palabras por minuto, "
            "una velocidad normal de tipeo. La velocidad es la de tu voz, no la de la escritura."))
        lay.addStretch(1)
        self._refresh_stats()
        return page

    def _metric(self, value, caption):
        box = card()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 16, 16, 16)
        n = QLabel(value)
        n.setObjectName("metric")
        c = muted(caption)
        lay.addWidget(n)
        lay.addWidget(c)
        return box, n

    def _set_tecla(self, value):
        self.tecla = value
        self.card_hold.set_on(value == "mantener")
        self.card_toggle.set_on(value == "alternar")

    def _set_modo(self, value):
        self.modo = value
        self.card_local.set_on(value == "local")
        self.card_online.set_on(value == "online")

    def _model_hint(self):
        self.model_hint.setText(MODEL_HINT.get(self.model.currentData(), "Si cambiás la calidad, la próxima vez se descarga."))

    def _fill_mics(self):
        saved = self.mic.currentData() if self.mic.count() else (cfg.get("microfono") or "")
        self.mic.blockSignals(True)
        self.mic.clear()
        self.mic.addItem("Predeterminado de Windows", "")
        try:
            for name, _idx in list_mics():
                self.mic.addItem(name, name)
        except Exception as e:
            log("mics ui", repr(e))
        if saved and self.mic.findData(saved) < 0:
            self.mic.addItem(f"{saved} (desconectado)", saved)
        i = self.mic.findData(saved if saved is not None else "")
        self.mic.setCurrentIndex(i if i >= 0 else 0)
        self.mic.blockSignals(False)

    def _mic_changed(self):
        if controller is not None and self.isVisible() and self.stack.currentIndex() == 2:
            controller.start_monitor(self.mic.currentData() or "")

    def _select_nav(self, index):
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)
        editing = index in (0, 1, 2)
        self.save_btn.setVisible(editing)
        self.footer_msg.setVisible(editing)
        self.footer.setVisible(editing)

    def open_page(self, index):
        self.stack.setCurrentIndex(index)
        self._select_nav(index)
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_page(self, index):
        self._select_nav(index)
        if index == 3:
            self._refresh_history()
        elif index == 4:
            self._refresh_stats()
        if controller is not None:
            if index == 2 and self.isVisible():
                controller.start_monitor(self.mic.currentData() or "")
            else:
                controller.stop_monitor()

    def _refresh_lists(self):
        self._refresh_history()
        self._refresh_stats()

    def _refresh_update(self):
        if update.get("url"):
            self.update_btn.setText(f"Instalar versión {update.get('ver')}")
            self.update_btn.setObjectName("primary")
            self.update_btn.style().unpolish(self.update_btn)
            self.update_btn.style().polish(self.update_btn)
            self.update_hint.setText("Hay una versión nueva. Se instala encima de esta.")
        else:
            self.update_btn.setText("Buscar actualizaciones")
            self.update_hint.setText("Estás al día.")

    def _update_click(self):
        if update.get("url"):
            self.update_btn.setEnabled(False)
            self.update_btn.setText("Descargando…")
            threading.Thread(target=install_update, daemon=True).start()
        else:
            threading.Thread(target=check_update, args=(True,), daemon=True).start()

    def _begin_capture(self):
        global capturing
        capturing = True
        self._capturing = True
        self.hk_btn.setText("Apretá la combinación…  Esc cancela")
        self.hk_label.setText("Esperando teclas")
        self.grabKeyboard()

    def _end_capture(self):
        global capturing
        if not self._capturing:
            return
        capturing = False
        self._capturing = False
        self.releaseKeyboard()
        self.hk_btn.setText("Cambiar atajo")
        self.hk_label.setText(pretty_hotkey(self.hotkey))

    def keyPressEvent(self, e):
        if not self._capturing:
            super().keyPressEvent(e)
            return
        if e.isAutoRepeat():
            return
        if e.key() == Qt.Key_Escape:
            self._end_capture()
            return
        name = _qt_key_name(e.key())
        if not name:
            return
        mods = []
        m = e.modifiers()
        if m & Qt.ControlModifier:
            mods.append("ctrl")
        if m & Qt.AltModifier:
            mods.append("alt")
        if m & Qt.ShiftModifier:
            mods.append("shift")
        if m & Qt.MetaModifier:
            mods.append("windows")
        self.hotkey = "+".join(mods + [name])
        self._end_capture()

    def _save(self):
        key = self.key.text().strip()
        modo = self.modo
        if modo == "online" and not key:
            self._alert(
                "Falta la clave",
                "Para dictar por internet necesitás pegar la clave de Groq. Mientras tanto dejo el modo de esta computadora.")
            modo = "local"
            self._set_modo("local")
        old_model = cfg.get("modelo")
        cfg.update(
            modo=modo, groq_key=key, pulir=self.sw_pulir.isChecked(),
            atajo=(self.hotkey or "ctrl+alt+space").strip().lower(),
            modo_tecla=self.tecla, modelo=self.model.currentData() or "small",
            estilo=self.style.currentData() or "mantener", idioma=self.lang.currentData() or "es",
            sonidos=self.sw_son.isChecked(), inicio_windows=self.sw_ini.isChecked(),
            microfono=self.mic.currentData() or "")
        save()
        if not set_autostart(cfg["inicio_windows"]):
            self._alert("Inicio con Windows", "Guardé el resto, pero no pude anotar el inicio automático. Probá de nuevo.")
        wanted = cfg["atajo"]
        if not register_hotkey(announce=False) or cfg.get("atajo") != wanted:
            self.hotkey = cfg.get("atajo") or "ctrl+alt+space"
            self.hk_label.setText(pretty_hotkey(self.hotkey))
            self._alert("Atajo", "Esa combinación no funciona. Probá otra o dejá Ctrl + Alt + Espacio.")
            if not hk:
                return
        if old_model != cfg["modelo"]:
            global _model
            _model = None
            self.footer_msg.setText("Listo. La próxima vez se prepara la calidad nueva.")
        else:
            self.footer_msg.setText("Guardado.")
        if cfg["modo"] == "local" or not cfg["groq_key"]:
            threading.Thread(target=_preload, daemon=True).start()
        QTimer.singleShot(2200, lambda: self.footer_msg.setText("El atajo, la voz y el micrófono se aplican al guardar."))

    def _alert(self, title, text):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.NoIcon)
        box.addButton("Entendido", QMessageBox.AcceptRole)
        box.exec()

    def _wipe_history(self):
        if not load_history():
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP)
        box.setText("¿Borrar todo el historial?")
        box.setInformativeText("Los textos se van de esta computadora. No se puede deshacer.")
        no = box.addButton("Cancelar", QMessageBox.RejectRole)
        yes = box.addButton("Borrar", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is yes:
            clear_history()

    def _refresh_history(self):
        while self.hist_box.count():
            item = self.hist_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        hist = load_history()
        if not hist:
            self.hist_box.addWidget(muted("Todavía no dictaste nada. Usá el atajo y hablá: el texto va a aparecer acá."))
            return
        for i, item in enumerate(hist[:100]):
            self.hist_box.addWidget(self._hist_card(i, item))

    def _hist_card(self, index, item):
        box = card()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        meta = muted(f"{fmt_when(item.get('ts', time.time()))}  ·  {fmt_int(item.get('words', words_in(item.get('text', ''))))} palabras")
        text = QLabel(item.get("text", ""))
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(meta)
        lay.addWidget(text)
        actions = QHBoxLayout()
        copy_b = button("Copiar", "chip")
        paste_b = button("Pegar de nuevo", "chip")
        del_b = button("Borrar", "danger")
        raw = item.get("text", "")
        copy_b.clicked.connect(lambda _=False, t=raw, b=copy_b: self._copy_text(t, b))
        paste_b.clicked.connect(lambda _=False, t=raw, b=paste_b: self._repaste(t, b))
        del_b.clicked.connect(lambda _=False, n=index: delete_history(n))
        actions.addWidget(copy_b)
        actions.addWidget(paste_b)
        actions.addWidget(del_b)
        actions.addStretch(1)
        lay.addLayout(actions)
        return box

    def _copy_text(self, text, btn):
        try:
            pyperclip.copy(text)
            self._flash(btn, "Copiado", "Copiar")
        except Exception as e:
            log("copy", repr(e))
            notify("No pude copiar el texto.")

    def _repaste(self, text, btn):
        def run():
            try:
                paste(text)
            except Exception as e:
                log("reinsert", repr(e))
                notify("No pude pegar. Hacé clic donde querés el texto y probá de nuevo.")
        threading.Thread(target=run, daemon=True).start()
        self._flash(btn, "Pegado", "Pegar de nuevo")

    def _flash(self, btn, text, restore):
        btn.setText(text)
        def back(b=btn, r=restore):
            try:
                b.setText(r)
            except RuntimeError:
                pass
        QTimer.singleShot(1200, back)

    def _refresh_stats(self):
        m = load_stats()
        words = int(m.get("words", 0) or 0)
        seconds = float(m.get("seconds", 0) or 0)
        self.m_words_n.setText(fmt_int(words))
        self.m_wpm_n.setText(fmt_int(wpm_of(words, seconds)))
        self.m_saved_n.setText(fmt_span(time_saved(words, seconds)))
        if int(m.get("sessions", 0) or 0) <= 0:
            self.last_label.setText("Todavía no hay dictados. Cuando hables, vas a ver acá cuánto ahorrás.")
            return
        lw, ls, lp = int(m.get("last_words", 0) or 0), float(m.get("last_seconds", 0) or 0), int(m.get("last_wpm", 0) or 0)
        self.last_label.setText(
            f"Último dictado: {fmt_int(lw)} palabras en {fmt_span(ls)} ({fmt_int(lp)} palabras por minuto). "
            f"En total, {fmt_int(m.get('sessions', 0))} dictados.")

    def showEvent(self, e):
        super().showEvent(e)
        self._dark_title()
        self._center()
        self._refresh_update()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self._capturing:
            self._end_capture()
        if controller is not None:
            controller.stop_monitor()

    def closeEvent(self, e):
        if self._capturing:
            self._end_capture()
        if controller is not None:
            controller.stop_monitor()
        e.accept()

    def _center(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(geo.center())
        self.move(frame.topLeft())

    def _dark_title(self):
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

def _qt_key_name(key):
    special = {
        Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Tab: "tab",
        Qt.Key_Backspace: "backspace", Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left",
        Qt.Key_Right: "right", Qt.Key_Delete: "delete", Qt.Key_Insert: "insert", Qt.Key_Home: "home",
        Qt.Key_End: "end", Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down",
    }
    if key in special:
        return special[key]
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"f{key - Qt.Key_F1 + 1}"
    if Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key).lower()
    return None

class App(QObject):
    def __init__(self, qapp):
        super().__init__()
        global controller
        controller = self
        self.app = qapp
        self.mon = None
        self.settings = None
        self.pill = Pill()
        self.tray = QSystemTrayIcon(make_tray_icon("cargando"))
        self.tray.setToolTip(f"{APP} — Preparando")
        self.menu = QMenu()
        self.act_ver = QAction(f"{APP}  {VERSION}", self.menu)
        self.act_ver.setEnabled(False)
        self.act_update = QAction("Instalar actualización", self.menu)
        self.act_update.setVisible(False)
        self.act_update.triggered.connect(lambda: threading.Thread(target=install_update, daemon=True).start())
        self.act_check = QAction("Buscar actualizaciones", self.menu)
        self.act_check.triggered.connect(lambda: threading.Thread(target=check_update, args=(True,), daemon=True).start())
        self.act_cfg = QAction("Configuración", self.menu)
        self.act_cfg.triggered.connect(lambda: self.open_settings(0))
        self.act_hist = QAction("Historial", self.menu)
        self.act_hist.triggered.connect(lambda: self.open_settings(3))
        self.act_stats = QAction("Métricas", self.menu)
        self.act_stats.triggered.connect(lambda: self.open_settings(4))
        self.act_log = QAction("Abrir registro de errores", self.menu)
        self.act_log.triggered.connect(self._open_log)
        self.act_quit = QAction("Salir", self.menu)
        self.act_quit.triggered.connect(self.quit)
        for act in (self.act_ver, self.act_update, self.act_check):
            self.menu.addAction(act)
        self.menu.addSeparator()
        self.menu.addAction(self.act_cfg)
        self.menu.addAction(self.act_hist)
        self.menu.addAction(self.act_stats)
        self.menu.addSeparator()
        self.menu.addAction(self.act_log)
        self.menu.addAction(self.act_quit)
        self.menu.aboutToShow.connect(self._sync_update_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.show()
        bridge.state_changed.connect(self._on_state)
        bridge.notice.connect(self._notice)
        bridge.update_ready.connect(self._sync_update_action)
        self._on_state("cargando" if (cfg.get("modo") == "local" or not cfg.get("groq_key")) else "listo", "")

    def _on_state(self, state, tip):
        self.pill.on_state(state, tip)
        icon_state = "grabando" if tip == "error" else state
        self.tray.setIcon(make_tray_icon(icon_state))
        names = {
            "grabando": "Escuchando", "procesando": "Procesando", "cargando": "Preparando la voz",
            "listo": "Listo", "corto": "Muy corto", "vacio": "No se escuchó", "error": "Error",
            "cancelado": "Cancelado", "actualizando": "Actualizando",
        }
        label = names.get(tip or state, "Listo")
        self.tray.setToolTip(f"{APP} — {label}")

    def _notice(self, msg):
        self.tray.showMessage(APP, msg, QSystemTrayIcon.MessageIcon.Information, 4500)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_settings(0)

    def _sync_update_action(self):
        ready = bool(update.get("url"))
        self.act_update.setVisible(ready)
        if ready:
            self.act_update.setText(f"Instalar actualización {update.get('ver')}")
        if self.settings is not None:
            self.settings._refresh_update()

    def open_settings(self, page=0):
        if self.settings is None:
            self.settings = Settings()
        self.settings.open_page(page)

    def _open_log(self):
        if not os.path.exists(LOG):
            notify("Todavía no hay errores anotados.")
            return
        try:
            if os.name == "nt":
                os.startfile(LOG)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", LOG])
        except Exception as e:
            log("log open", repr(e))

    def start_monitor(self, name):
        if recording:
            return
        with mic_lock:
            if recording:
                return
            self._stop_monitor()
            dev = resolve_device(name)

            def mon_cb(indata, n, t, status):
                if indata is None or indata.size == 0:
                    return
                peak = float(np.max(np.abs(indata))) / 32768.0
                if bridge is not None:
                    bridge.mic_level.emit(min(1.0, peak * 4.5))

            try:
                self.mon = sd.InputStream(samplerate=FS, channels=1, dtype="int16", callback=mon_cb, device=dev, blocksize=480)
                self.mon.start()
            except Exception as e:
                self.mon = None
                log("monitor", repr(e))
                if self.settings is not None:
                    self.settings.mic_msg.setText("No pude abrir ese micrófono. Probá el predeterminado u otro de la lista.")

    def _stop_monitor(self):
        if self.mon is not None:
            try:
                self.mon.stop()
                self.mon.close()
            except Exception:
                pass
            self.mon = None

    def stop_monitor(self):
        with mic_lock:
            self._stop_monitor()

    def maybe_monitor(self):
        if self.settings is None or not self.settings.isVisible() or self.settings.stack.currentIndex() != 2:
            return
        if recording:
            return
        self.start_monitor(self.settings.mic.currentData() or "")

    def quit(self):
        self.stop_monitor()
        try:
            if hk:
                keyboard.remove_hotkey(hk)
        except Exception:
            pass
        self.tray.hide()
        self.app.quit()

def _preload():
    try:
        local_model()
    except Exception as e:
        log("modelo", repr(e))
        set_state("listo", "")
        notify("No pude preparar la voz. Podés reintentar o usar el modo por internet.")

def _dialog(title, text, button):
    box = QMessageBox()
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.NoIcon)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    ok = box.addButton(button, QMessageBox.AcceptRole)
    box.exec()
    return box.clickedButton() is ok

def _welcome():
    _dialog(
        APP,
        f"¡Hola!\n\nMantené apretado {pretty_hotkey(cfg.get('atajo') or 'ctrl+alt+space')} mientras hablás y soltalo: el texto aparece donde esté el cursor.\n\n"
        "Abajo, en el centro, vas a ver una pastilla con la onda de tu voz.\n\n"
        "La primera vez se descarga el modelo (unos 480 MB). El ícono junto al reloj queda gris mientras tanto y verde cuando está listo. "
        "Rojo significa que te está escuchando.\n\n"
        "Si querés, en Configuración podés pegar una clave gratis de Groq para dictar más rápido por internet.",
        "Entendido")

def _whats_new():
    if _dialog(
        APP,
        "Dictado Libre se actualizó.\n\nCuando dictás, aparece una pastilla abajo en el centro con la onda de tu voz.\n\n"
        "El historial, el micrófono y tus números están en el ícono junto al reloj.",
        "Abrir configuración"):
        if controller is not None:
            controller.open_settings(0)

def main():
    global bridge
    if os.name == "nt":
        global _mutex
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "DictadoLibreMutex")
        if ctypes.windll.kernel32.GetLastError() == 183:
            ctypes.windll.user32.MessageBoxW(0, "Dictado Libre ya está abierto. Mirá el ícono junto al reloj.", APP, 0x40)
            return
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setFont(app_font())
    app.setStyleSheet(APP_QSS)
    ico = resource("icon.ico")
    app.setWindowIcon(QIcon(ico) if os.path.exists(ico) else make_tray_icon("listo"))
    bridge = Bridge()
    App(app)
    register_hotkey()
    threading.Thread(target=update_loop, daemon=True).start()
    if cfg.get("modo") == "local" or not cfg.get("groq_key"):
        threading.Thread(target=_preload, daemon=True).start()
    else:
        set_state("listo", "")
    if cfg.get("primera_vez"):
        cfg["primera_vez"] = False
        save()
        QTimer.singleShot(400, lambda: (_welcome(), controller.open_settings(0)))
    elif cfg.pop("_from_old", False):
        save()
        QTimer.singleShot(500, _whats_new)
    code = app.exec()
    try:
        if controller is not None:
            controller.stop_monitor()
    except Exception:
        pass
    os._exit(code)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("fatal", repr(e))
        raise
