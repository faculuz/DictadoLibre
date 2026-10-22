# Dictado Libre - dictado por voz gratuito para Windows (local u online con Groq)
import os, sys, json, time, threading, tempfile, re, io, wave, math, ctypes
from datetime import datetime, timedelta
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
import requests
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRectF, QUrl, QPoint, QPointF
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen, QFont, QFontDatabase, QAction,
    QDesktopServices, QGuiApplication, QLinearGradient, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, QStackedWidget, QSystemTrayIcon, QMenu,
    QMessageBox, QScrollArea, QPlainTextEdit, QLayout, QSizePolicy,
)

APP = "Dictado Libre"
VERSION = "1.4.0"
REPO = "faculuz/DictadoLibre"
AUMID = "FacundoLuzardo.DictadoLibre"
DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DictadoLibre")
AUDIOS = os.path.join(DIR, "audios")
os.makedirs(DIR, exist_ok=True)
os.makedirs(AUDIOS, exist_ok=True)
AUDIO_TTL = 24 * 3600
AUDIO_MAX_FILES = 40
CFG = os.path.join(DIR, "config.json")
LOG = os.path.join(DIR, "registro.txt")
HIST = os.path.join(DIR, "historial.json")
STATS = os.path.join(DIR, "metricas.json")
FS = 16000
TYPING_WPM = 40
BAR_N = 12
DEFAULT = {
    "modo": "local", "groq_key": "", "pulir": True, "atajo": "ctrl+alt+space",
    "atajo_cmd": "ctrl+alt+shift+space", "atajo_escribir": "ctrl+alt+a",
    "modo_tecla": "mantener", "estilo": "mantener", "tono": "auto", "modelo": "small", "idioma": "es",
    "sonidos": True, "inicio_windows": False, "primera_vez": True, "microfono": "",
    "traducir_en": False, "tonos": {},
    "diccionario": [], "fragmentos": [], "susurro": False, "privacidad": False, "aprender": True,
    "pill_x": None, "pill_y": None,
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
LANGS = [
    ("es", "Español"),
    ("multi", "Multilingüe (Español / Inglés)"),
    ("en", "Inglés"),
    ("pt", "Portugués"),
]
ESTILOS = {
    "mantener": "No cambies el tono: solo limpiá el dictado.",
    "formal": "Tono formal, de correo o documento de trabajo. Tratamiento de usted, frases completas.",
    "mensaje": "Mensaje de chat: breve, natural, voseo, cercano. Sin saludos largos si no hacen falta.",
    "tecnico": "Tono técnico, para código o una nota de trabajo. Preciso, sin adornos. Dejá en inglés los términos técnicos.",
}
APP_RULES = [
    ("outlook.exe", "formal", "Correo (Outlook)"),
    ("olk.exe", "formal", "Correo (Outlook nuevo)"),
    ("thunderbird.exe", "formal", "Correo (Thunderbird)"),
    ("winword.exe", "formal", "Word"),
    ("powerpnt.exe", "formal", "PowerPoint"),
    ("whatsapp.exe", "mensaje", "WhatsApp"),
    ("whatsapp.root.exe", "mensaje", "WhatsApp (Store)"),
    ("slack.exe", "mensaje", "Slack"),
    ("teams.exe", "mensaje", "Teams"),
    ("ms-teams.exe", "mensaje", "Teams (nuevo)"),
    ("telegram.exe", "mensaje", "Telegram"),
    ("code.exe", "tecnico", "Visual Studio Code"),
    ("cursor.exe", "tecnico", "Cursor"),
    ("devenv.exe", "tecnico", "Visual Studio"),
    ("windowsterminal.exe", "tecnico", "Terminal"),
    ("notepad++.exe", "tecnico", "Notepad++"),
]
DEFAULT_TONOS = {exe: tone for exe, tone, _name in APP_RULES}
APP_NAMES = {exe: name for exe, _tone, name in APP_RULES}
TONE_EDIT = [("mantener", "Como lo dije"), ("formal", "Formal"), ("mensaje", "Chat"), ("tecnico", "Técnico")]
TONE_ALL = [("auto", "Según la aplicación")] + TONE_EDIT
DICT_TYPES = [("nombre", "Nombre"), ("sigla", "Sigla"), ("jerga", "Jerga")]
WEEKDAYS = r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo"
HOUR_WORDS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
              "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12}
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

def _clean_dict_entries(raw):
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            item = {"escribe": item}
        if not isinstance(item, dict):
            continue
        escribe = " ".join(str(item.get("escribe") or item.get("palabra") or "").split())
        if not escribe or len(escribe) > 80:
            continue
        oye = " ".join(str(item.get("oye") or "").split())[:80]
        tipo = item.get("tipo") if item.get("tipo") in ("nombre", "sigla", "jerga") else "jerga"
        key = escribe.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"escribe": escribe, "oye": oye, "tipo": tipo})
        if len(out) >= 200:
            break
    return out

def _clean_snippets(raw):
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        frase = " ".join(str(item.get("frase") or "").split())
        texto = str(item.get("texto") or "").strip()
        if not frase or not texto or len(frase) > 80 or len(texto) > 4000:
            continue
        key = frase.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"frase": frase, "texto": texto})
        if len(out) >= 80:
            break
    return out

def load():
    raw = _read_json(CFG, {})
    if not isinstance(raw, dict):
        raw = {}
    c = dict(DEFAULT)
    c.update(raw)
    if "tono" not in raw:
        est = raw.get("estilo", "mantener")
        c["tono"] = est if est in ("formal", "mensaje", "tecnico") else "auto"
    if not isinstance(c.get("tonos"), dict):
        c["tonos"] = {}
    c["diccionario"] = _clean_dict_entries(c.get("diccionario"))
    c["fragmentos"] = _clean_snippets(c.get("fragmentos"))
    c["susurro"] = bool(c.get("susurro"))
    c["privacidad"] = bool(c.get("privacidad"))
    c["aprender"] = bool(c.get("aprender", True))
    fresh = not c.get("primera_vez", True) and os.path.exists(CFG)
    c["_from_old"] = fresh and "microfono" not in raw
    c["_from_12"] = fresh and "atajo_cmd" not in raw
    c["_from_13"] = fresh and "diccionario" not in raw
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

def cleanup_old_audios():
    try:
        now = time.time()
        files = []
        for name in os.listdir(AUDIOS):
            if not name.lower().endswith(".wav"):
                continue
            p = os.path.join(AUDIOS, name)
            try:
                mt = os.path.getmtime(p)
                if now - mt > AUDIO_TTL:
                    os.remove(p)
                else:
                    files.append((mt, p))
            except Exception:
                pass
        files.sort(reverse=True)
        for _mt, p in files[AUDIO_MAX_FILES:]:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        pass

def remember(text, seconds, audio_path=None):
    w = words_in(text)
    ts = time.time()
    item = {"ts": ts, "text": text, "words": w, "seconds": round(float(seconds), 2)}
    if audio_path:
        item["audio"] = audio_path
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
    return ts

def update_history_text(ts, text, seconds=0.0, audio_path=None):
    if not (text or "").strip():
        return None
    w = words_in(text)
    updated_ts = ts
    with _store_lock:
        hist = load_history()
        found = False
        for item in hist:
            if (ts and abs(float(item.get("ts", 0)) - float(ts)) < 1e-4) or (audio_path and item.get("audio") == audio_path):
                item["text"] = text
                item["words"] = w
                if audio_path:
                    item["audio"] = audio_path
                updated_ts = item.get("ts", ts)
                found = True
                break
        if not found:
            updated_ts = time.time()
            entry = {"ts": updated_ts, "text": text, "words": w, "seconds": round(float(seconds), 2)}
            if audio_path:
                entry["audio"] = audio_path
            hist.insert(0, entry)
            del hist[200:]
        _write_json(HIST, hist)
    if bridge is not None:
        bridge.history_changed.emit()
    return updated_ts

def delete_history(index):
    with _store_lock:
        hist = load_history()
        if 0 <= index < len(hist):
            removed = hist.pop(index)
            ap = removed.get("audio") if isinstance(removed, dict) else None
            if ap and os.path.exists(ap):
                try:
                    os.remove(ap)
                except Exception:
                    pass
            _write_json(HIST, hist)
    if bridge is not None:
        bridge.history_changed.emit()

def clear_history():
    with _store_lock:
        _write_json(HIST, [])
        try:
            for name in os.listdir(AUDIOS):
                if name.lower().endswith(".wav"):
                    try:
                        os.remove(os.path.join(AUDIOS, name))
                    except Exception:
                        pass
        except Exception:
            pass
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
hotkeys = {}
capturing = False
session_kind = "dictado"
session_tone = "mantener"
learn_gen = 0
mic_lock = threading.RLock()
level_lock = threading.Lock()
levels = [0.06] * BAR_N
update = {"ver": None, "url": None}
paste_lock = threading.Lock()
last_recording = {"audio": None, "kind": "dictado", "tone": "mantener", "ts": None, "seconds": 0.0}

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

def _word_pat(term):
    return r"(?i)(?<!\w)" + re.escape(term.strip()) + r"(?!\w)"

def whisper_prompt():
    lang = cfg.get("idioma") or "es"
    if lang == "multi":
        base = "Hola, ¿cómo estás? This is a bilingual dictation in Spanish and English, manteniendo cada frase en su idioma original."
    elif lang == "en":
        base = "Hello, how are you? This is a dictation in English with proper punctuation."
    elif lang == "pt":
        base = "Olá, tudo bem? Este é um ditado em português com pontuação correta."
    else:
        base = "Hola, ¿cómo estás? Esto es un dictado en español, con puntuación correcta."
    words = []
    for entry in cfg.get("diccionario") or []:
        word = " ".join(str(entry.get("escribe") or "").split())
        if word and word not in words:
            words.append(word)
    if not words:
        return base
    extra = ", ".join(words)
    if len(extra) > 350:
        extra = extra[:350].rsplit(",", 1)[0]
    return base + " Nombres y términos: " + extra + "."

def vocab_clause():
    bits = []
    for entry in cfg.get("diccionario") or []:
        write = (entry.get("escribe") or "").strip()
        if not write:
            continue
        heard = (entry.get("oye") or "").strip()
        if heard and heard.lower() != write.lower():
            bits.append(f"«{heard}» se escribe «{write}»")
        else:
            bits.append(write)
        if len(bits) >= 40:
            break
    if not bits:
        return ""
    line = " Vocabulario de esta persona: respetalo tal cual. " + "; ".join(bits) + "."
    return line[:1500]

def snippet_clause():
    bits = []
    for item in cfg.get("fragmentos") or []:
        frase = (item.get("frase") or "").strip()
        if frase:
            bits.append(f"«{frase}»")
        if len(bits) >= 20:
            break
    if not bits:
        return ""
    return " No reescribas estas frases, dejálas literales: " + ", ".join(bits) + "."

def apply_dictionary(text):
    out = text or ""
    entries = [e for e in (cfg.get("diccionario") or []) if (e.get("oye") or "").strip() and (e.get("escribe") or "").strip()]
    entries.sort(key=lambda e: len(e.get("oye") or ""), reverse=True)
    for entry in entries:
        heard, write = entry["oye"].strip(), entry["escribe"].strip()
        if heard.lower() == write.lower():
            continue
        out = re.sub(_word_pat(heard), lambda _m, write=write: write, out)
    return out

def exact_snippet(raw):
    folded = " ".join((raw or "").split()).strip(" .!?¡¿")
    if not folded:
        return None
    for item in cfg.get("fragmentos") or []:
        frase = " ".join((item.get("frase") or "").split()).strip(" .!?¡¿")
        if frase and folded.lower() == frase.lower():
            return item.get("texto") or ""
    return None

def apply_snippets(text):
    out = text or ""
    items = [s for s in (cfg.get("fragmentos") or []) if (s.get("frase") or "").strip() and (s.get("texto") or "").strip()]
    items.sort(key=lambda s: len(s["frase"]), reverse=True)
    parked = []
    for i, item in enumerate(items):
        token = f"\u0000SN{i}\u0000"
        expansion = item["texto"]

        def repl(_m, token=token, expansion=expansion):
            parked.append((token, expansion))
            return token

        out = re.sub(_word_pat(item["frase"].strip()) + r"\s*[.!?¡¿]?", repl, out)
    for token, expansion in parked:
        out = out.replace(token, expansion)
    return out

def prepare_audio(audio):
    audio = np.asarray(audio)
    if audio.size == 0:
        return np.zeros(0, np.int16)
    original = audio.astype(np.int16, copy=False)
    if not cfg.get("susurro"):
        return original
    samples = original.astype(np.float32)
    samples -= float(np.mean(samples))
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak < 180:
        return original
    target = 14000.0
    if peak >= target:
        return original
    samples *= min(10.0, target / peak)
    np.clip(samples, -32767, 32767, out=samples)
    return samples.astype(np.int16)

def chunk_level(chunk):
    if chunk is None or getattr(chunk, "size", 0) == 0:
        return 0.0
    peak = float(np.max(np.abs(chunk))) / 32768.0
    boost = 18.0 if cfg.get("susurro") else 9.5
    scaled = min(1.0, peak * boost)
    return scaled ** 0.72

def transcribe_local(audio):
    audio = prepare_audio(audio)
    lang = cfg.get("idioma") or None
    is_multi = (lang == "multi")
    if is_multi:
        lang = None
    kwargs = dict(
        language=lang, task="transcribe", beam_size=5, vad_filter=True, initial_prompt=whisper_prompt())
    if is_multi:
        kwargs["multilingual"] = True
    if cfg.get("susurro"):
        kwargs["vad_parameters"] = dict(
            threshold=0.22, min_speech_duration_ms=80, min_silence_duration_ms=700, speech_pad_ms=480)
    try:
        segs, _ = local_model().transcribe(audio.astype(np.float32) / 32768.0, **kwargs)
    except TypeError:
        kwargs.pop("multilingual", None)
        segs, _ = local_model().transcribe(audio.astype(np.float32) / 32768.0, **kwargs)
    return " ".join(s.text.strip() for s in segs).strip()

def wav_bytes(audio):
    audio = np.asarray(audio, dtype=np.int16)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(audio.tobytes())
    return b.getvalue()

def save_recording_audio(audio):
    try:
        cleanup_old_audios()
        os.makedirs(AUDIOS, exist_ok=True)
        path = os.path.join(AUDIOS, f"rec_{int(time.time() * 1000)}.wav")
        with open(path, "wb") as f:
            f.write(wav_bytes(audio))
        return path
    except Exception as e:
        log("guardar audio", repr(e))
        return None

def load_recording_audio(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with wave.open(path, "rb") as w:
            raw = w.readframes(w.getnframes())
        return np.frombuffer(raw, dtype=np.int16).copy()
    except Exception as e:
        log("leer audio", repr(e))
        return None

def transcribe_groq(audio):
    audio = prepare_audio(audio)
    lang = cfg.get("idioma") or ""
    data = {
        "model": "whisper-large-v3-turbo",
        "response_format": "json",
        "prompt": whisper_prompt()[:500],
    }
    if lang and lang != "multi":
        data["language"] = lang
    r = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": "Bearer " + cfg["groq_key"].strip()},
        files={"file": ("a.wav", wav_bytes(audio), "audio/wav")},
        data=data,
        timeout=30)
    r.raise_for_status()
    return r.json()["text"].strip()

_REFUSAL_PAT = re.compile(
    r"(?is)^\s*(?:"
    r"lo\s+siento[,.\s]|"
    r"disculp[aáe][,.\s]|"
    r"perd[oó]n[,.\s]+(?:pero\s+)?no\s+puedo|"
    r"no\s+puedo\s+(?:ayudar|cumplir|procesar|asistir|generar|traducir|redactar|responder|completar|hacer\s+eso)|"
    r"lamentablemente\s+no\s+puedo|"
    r"como\s+(?:modelo\s+de\s+(?:lenguaje|ia)|inteligencia\s+artificial|asistente)|"
    r"i'?m\s+sorry[,.\s]|"
    r"sorry[,.\s]+(?:but\s+)?i\s+(?:can'?t|cannot)|"
    r"i\s+(?:can'?t|cannot)\s+(?:fulfill|assist|help|comply|provide|generate|process|complete|translate)|"
    r"as\s+an\s+ai\b|"
    r"error\s*:|"
    r"no\s+se\s+proporcion[oó]\s+(?:ning[uú]n\s+)?texto|"
    r"no\s+hay\s+(?:ning[uú]n\s+)?texto\s+para"
    r")"
)

def is_ai_refusal_or_error(out, raw=""):
    t = (out or "").strip()
    if not t:
        return True
    if _REFUSAL_PAT.search(t) and not _REFUSAL_PAT.search(raw or ""):
        return True
    return False

def groq_text(system, user, timeout=45):
    key = (cfg.get("groq_key") or "").strip()
    if not key:
        raise RuntimeError("sin clave")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json={
            "model": "openai/gpt-oss-120b",
            "temperature": 0.3,
            "reasoning_effort": "low",
            "include_reasoning": False,
            "max_completion_tokens": 8192,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user[:12000]}],
        },
        timeout=timeout)
    r.raise_for_status()
    choice = (r.json().get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    out = (msg.get("content") or "").strip()
    if choice.get("finish_reason") == "length" and not out:
        raise RuntimeError("respuesta vacía")
    parts = re.split(r"(?is)<\|channel\|>final<\|message\|>", out)
    if len(parts) > 1:
        out = parts[-1]
    out = re.sub(r"<\|[^|>]*\|>", "", out).strip()
    out = re.sub(r"^```(?:\w+)?\s*", "", out)
    out = re.sub(r"\s*```$", "", out)
    out = re.sub(r"(?i)^(texto final|resultado|mensaje)\s*:\s*", "", out).strip()
    if len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'":
        out = out[1:-1].strip()
    if is_ai_refusal_or_error(out, user):
        raise RuntimeError("rechazo o respuesta inválida del modelo")
    return out

def remove_fillers(t):
    t = re.sub(r"(?i)^(?:bueno|este|eh+|em+|ehm+)\s*,\s*", "", t or "")
    t = re.sub(r"(?i)\b(eh+|em+|ehm+|mm+|mmm+|este\.\.\.|o sea|osea|digamos)\b[,.]?\s*", "", t)
    t = re.sub(r"(?i)\btipo\b(?=\s*[,.])\s*", "", t)
    return t

def resolve_corrections(t):
    patterns = [
        r"(?is)^.*(?:\.{2,}|…)\s*no\b[, ]+(?:mejor\s+|perdón\s+|perdis\s+|digo\s+|quise decir\s+)?(.+)$",
        r"(?is)^.*\bno\b[, ]+(?:mejor|perdón|perdis|digo|quise decir)\s+(.+)$",
    ]
    cur = (t or "").strip()
    for _ in range(3):
        nxt = None
        for p in patterns:
            m = re.match(p, cur)
            if m:
                nxt = m.group(1).strip(" .,")
                break
        if not nxt or nxt == cur:
            break
        cur = nxt
    return cur

def normalize_times(t):
    def repl(m):
        raw_h = m.group(1).lower()
        hour = int(raw_h) if raw_h.isdigit() else HOUR_WORDS.get(raw_h)
        if not hour or hour > 12:
            return m.group(0)
        extra = (m.group(2) or "").lower()
        daypart = (m.group(3) or "").lower()
        if "mañana" in daypart or daypart.strip() == "am":
            hh = 0 if hour == 12 else hour
        elif "tarde" in daypart or "noche" in daypart or daypart.strip() == "pm":
            hh = hour if hour >= 12 else hour + 12
        elif hour <= 7 and re.search(r"(?i)\b(" + WEEKDAYS + r")\b", t):
            hh = hour + 12
        else:
            hh = hour
        if "menos" in extra:
            hh = (hh - 1) % 24
            mm = 45
        elif "media" in extra:
            mm = 30
        elif "cuarto" in extra:
            mm = 15
        else:
            mm = 0
        changed = hh != hour or mm or daypart or extra
        if not changed:
            return m.group(0)
        return f"a las {hh}:{mm:02d}"
    return re.sub(
        r"(?i)\ba\s+las\s+(\d{1,2}|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)"
        r"(?:\s+((?:y\s+(?:media|cuarto))|(?:menos\s+cuarto)))?"
        r"(?:\s+((?:de\s+la\s+(?:mañana|tarde|noche))|(?:am|pm)))?",
        repl, t or "")

def format_structure(t):
    t = re.sub(r"\s*(?:punto y aparte|nuevo p[aá]rrafo)\s*[.,]?\s*", ".\n\n", t or "", flags=re.I)
    t = re.sub(r"\s*(?:nueva l[ií]nea|salto de l[ií]nea)\s*[.,]?\s*", "\n", t, flags=re.I)
    t = t.replace("..\n", ".\n")
    if re.search(r"(?i)\bviñetas?\b", t):
        raw_parts = re.split(r"(?i)\s*viñetas?\s*[:,.]?\s*", t)
        started = not raw_parts[0].strip(" .,")
        parts = [p.strip(" .,") for p in raw_parts if p.strip(" .,")]
        if parts and re.fullmatch(r"(?i)(?:una\s+)?lista|hac[eé]\s+una\s+lista|quiero\s+una\s+lista", parts[0]):
            parts = parts[1:]
            started = True
        if parts and (started or len(parts) >= 2):
            head, items = ("", parts) if started else (parts[0], parts[1:])
            if re.fullmatch(r"(?i)(?:una\s+)?lista|hac[eé]\s+una\s+lista|quiero\s+una\s+lista", head or ""):
                head = ""
            if items:
                body = "\n".join(f"- {x[:1].upper() + x[1:]}" for x in items)
                return (head + "\n" + body).strip() if head else body
    if len(re.findall(r"(?i)\b(primero|segundo|tercero|cuarto|quinto|sexto)\b", t)) >= 2:
        parts = re.split(r"(?i)\s*(?:primero|segundo|tercero|cuarto|quinto|sexto)\s*[:,.]?\s*", t)
        items = []
        for p in parts:
            p = re.sub(r"(?i)\s+y$", "", p.strip(" .,")).strip()
            if p:
                items.append(p)
        if len(items) >= 2:
            intro, rows = "", items
            if not re.match(r"(?i)^(?:primero)\b", t.strip()) and len(items) >= 3:
                intro, rows = items[0], items[1:]
            body = "\n".join(f"{i}. {x[:1].upper() + x[1:]}" for i, x in enumerate(rows, 1))
            return (intro + "\n" + body).strip() if intro else body
    return t

def capitalize_blocks(t):
    out = []
    for block in re.split(r"(\n+)", t or ""):
        if not block or block.startswith("\n"):
            out.append(block)
            continue
        m = re.match(r"^(\s*(?:-\s+|\d+\.\s+)?)(.*)$", block, re.S)
        prefix, body = (m.group(1), m.group(2)) if m else ("", block)
        body = body.strip()
        if body:
            body = body[:1].upper() + body[1:]
            if not re.match(r"^(?:-\s+|\d+\.\s+)", prefix or "") and body[-1] not in ".!?…:":
                body += "."
        out.append((prefix or "") + body)
    return "".join(out).strip()

def polish_text_local(t, tone="mantener"):
    t = remove_fillers(t)
    t = resolve_corrections(t)
    t = normalize_times(t)
    t = format_structure(t)
    t = re.sub(r"(?i)\b(\w+)( \1\b)+", r"\1", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" *\n *", "\n", t).strip()
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = capitalize_blocks(t)
    if tone == "tecnico":
        t = re.sub(r"(?m)^(-\s+|\d+\.\s+)?", r"\1", t)
    return t

def polish_local(t):
    return polish_text_local(t, "mantener")

def command_local(selected, instruction):
    ins = (instruction or "").lower()
    if re.search(r"ingl[eé]s|traduc", ins):
        return None
    if re.search(r"may[uú]scul", ins):
        return selected.upper()
    if re.search(r"min[uú]scul", ins):
        return selected.lower()
    lines = [ln.strip() for ln in re.split(r"[\n;]+|(?<=\.)\s+", selected) if ln.strip()]
    if re.search(r"viñet|lista|bullet", ins):
        return "\n".join(f"- {ln.rstrip('.')}" for ln in lines) if lines else selected
    if re.search(r"numer", ins):
        return "\n".join(f"{i}. {ln.rstrip('.')}" for i, ln in enumerate(lines, 1)) if lines else selected
    if re.search(r"p[aá]rrafo", ins):
        return "\n\n".join(ln.rstrip(".") + "." for ln in lines) if lines else selected
    return polish_text_local(selected, "mantener")

def help_local(instruction, tone):
    t = remove_fillers(instruction or "")
    t = resolve_corrections(t)
    t = normalize_times(t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .")
    name, body = None, ""
    m = re.search(r"(?i)(?:escribile|decile|mandale|avisale)\s+a\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+que\s+(.+)", t)
    if m:
        name, body = m.group(1), m.group(2)
        name = name[:1].upper() + name[1:]
    else:
        m2 = re.search(r"(?i)^(?:escrib[ií]|redact[aá]|arm[aá]|hac[eé])(?:me|le)?(?:\s+un)?(?:\s+(?:mensaje|mail|correo|texto))?(?:\s+para\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+)?\s*(?:que\s+|sobre\s+|de\s+que\s+)?(.+)", t)
        body = m2.group(1) if m2 else t
    body = body.strip(" .")
    if not body:
        return ""
    sentence = body[:1].upper() + body[1:]
    if sentence[-1] not in ".!?":
        sentence += "."
    low = sentence[:1].lower() + sentence[1:]
    if tone == "formal":
        who = f" {name}" if name else ""
        return f"Hola{who},\n\nTe escribo para contarte que {low}"
    if tone == "tecnico":
        return sentence
    if name:
        return f"Hola {name}, {low}"
    return sentence

def tone_for_name(proc):
    choice = cfg.get("tono") or "auto"
    if choice != "auto":
        return choice
    name = (proc or "").lower()
    custom = cfg.get("tonos") if isinstance(cfg.get("tonos"), dict) else {}
    merged = dict(DEFAULT_TONOS)
    merged.update({str(k).lower(): v for k, v in custom.items()})
    return merged.get(name, "mantener")

def active_process_name():
    if os.name != "nt":
        return ""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ""
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        kernel32.CloseHandle(handle)
        return os.path.basename(buf.value) if ok else ""
    except Exception as e:
        log("proceso", repr(e))
        return ""

def tone_now():
    return tone_for_name(active_process_name())

def _english_line(on):
    if cfg.get("idioma") == "multi":
        return (
            " Modo bilingüe (español/inglés): mantené cada frase, oración y término exactamente "
            "en el idioma en que se dijo. NUNCA traduzcas de español a inglés ni de inglés a español."
        )
    return " El texto final tiene que estar en inglés natural, listo para pegar." if on else " El texto final queda en español."

def prompt_dictado(tone):
    multi = cfg.get("idioma") == "multi"
    intro = (
        "Sos un editor de dictado bilingüe (español rioplatense e inglés). Recibís texto transcrito por voz, no una pregunta.\n"
        if multi else
        "Sos un editor de dictado en español rioplatense. Recibís texto transcrito por voz, no una pregunta.\n"
    )
    multi_rule = (
        "- Mantené cada frase o parte de la oración en el idioma exacto en que fue dicha (español o inglés). Prohibido traducir.\n"
        if multi else ""
    )
    return (
        intro +
        "Reglas:\n"
        "- Quitá muletillas (eh, este, o sea, mmm, digamos, um, uh, like) y repeticiones.\n"
        "- Si la persona se corrige, dejá solo la versión final. Ejemplo: "
        "'martes... no, mejor jueves a las 4' se escribe 'jueves a las 16:00'. "
        "Las horas de una cita (a las 1 a a las 7), si no dice 'de la mañana', van en 24 horas.\n"
        "- Si pide párrafos ('punto y aparte', 'nuevo párrafo') o una lista ('viñeta', 'primero, segundo'), "
        "formateá con saltos de línea, '- ' o '1. '.\n"
        + multi_rule +
        "- No inventes datos, no respondas preguntas, nunca des mensajes de disculpa o rechazo y no agregues explicaciones. Devolvé solo el texto final.\n"
        "- " + ESTILOS.get(tone, ESTILOS["mantener"]) + _english_line(cfg.get("traducir_en"))
        + vocab_clause() + snippet_clause())

def prompt_command(tone):
    return (
        "Tenés un texto que la persona seleccionó y una instrucción dicha en voz alta. "
        "Aplicá la instrucción a ese texto y devolvé solo el resultado, sin comillas ni explicación. "
        "Podés corregir, resumir, cambiar el tono, traducir, pasar a viñetas o reescribir. "
        "No inventes datos que no estén en el texto o en la instrucción y nunca respondas con disculpas o rechazos.\n"
        "- " + ESTILOS.get(tone, ESTILOS["mantener"]) + _english_line(cfg.get("traducir_en"))
        + vocab_clause())

def prompt_escribir(tone):
    return (
        "La persona dictó una instrucción corta para redactar un mensaje. Escribí el mensaje completo, listo para enviar. "
        "No expliques lo que hiciste, ni des mensajes de rechazo o disculpa. No inventes nombres, fechas, lugares ni números que no estén en la instrucción.\n"
        "- " + ESTILOS.get(tone, ESTILOS["mantener"]) + _english_line(cfg.get("traducir_en"))
        + vocab_clause())

def _cloud_key():
    return bool((cfg.get("groq_key") or "").strip()) and not cfg.get("privacidad")

def _spanish_notice():
    if cfg.get("privacidad"):
        return "La privacidad está activa, así que no uso Groq. Dejé el texto en su idioma original."
    return "Para escribir en inglés hace falta la clave gratis de Groq. Dejé el texto en su idioma original."

def shape_text(raw, kind, selected, tone):
    raw_clean = (raw or "").strip()
    if not raw_clean:
        return ""
    is_multi = cfg.get("idioma") == "multi"
    english = bool(cfg.get("traducir_en")) and not is_multi
    has_key = _cloud_key()
    if kind == "dictado" and not cfg.get("pulir", True):
        text = raw_clean
        if english and has_key:
            try:
                cand = groq_text("Traducí el texto al inglés natural. Devolvé solo la traducción, sin comillas.", text)
                if cand and not is_ai_refusal_or_error(cand, raw_clean):
                    return cand
            except Exception as e:
                log("traduccion", e)
                notify("Groq no respondió. Dejé la transcripción cruda.")
        elif english:
            notify(_spanish_notice())
        return text
    elif has_key:
        try:
            if kind == "comando":
                user = f"Texto seleccionado:\n{selected}\n\nInstrucción de voz:\n{raw_clean}"
                text = groq_text(prompt_command(tone), user)
            elif kind == "escribir":
                text = groq_text(prompt_escribir(tone), raw_clean)
            else:
                text = groq_text(prompt_dictado(tone), raw_clean)
            if text and not is_ai_refusal_or_error(text, raw_clean):
                return text
        except Exception as e:
            log("llm", repr(e))
            if "rechazo" in str(e).lower():
                return raw_clean
            if english or kind != "dictado":
                notify("Groq no respondió. Sigo con el modo offline en esta computadora.")
    elif english and kind == "dictado":
        notify(_spanish_notice())
    if kind == "comando":
        text = command_local(selected, raw_clean)
        if text is None or is_ai_refusal_or_error(text, raw_clean):
            return raw_clean
        if english and not has_key:
            notify(_spanish_notice())
        return text
    if kind == "escribir":
        if english and not has_key:
            notify(_spanish_notice())
        out = help_local(raw_clean, tone)
        return out if (out and not is_ai_refusal_or_error(out, raw_clean)) else raw_clean
    out = polish_text_local(raw_clean, tone)
    return out if (out and not is_ai_refusal_or_error(out, raw_clean)) else raw_clean

def grab_selection():
    with paste_lock:
        try:
            old = pyperclip.paste()
        except Exception:
            old = ""
        try:
            pyperclip.copy("")
        except Exception:
            return ""
        for _ in range(30):
            try:
                if not any(keyboard.is_pressed(k) for k in ("ctrl", "alt", "shift", "windows")):
                    break
            except Exception:
                break
            time.sleep(0.04)
        try:
            keyboard.send("ctrl+c")
        except Exception as e:
            log("seleccion", repr(e))
            try:
                pyperclip.copy(old or "")
            except Exception:
                pass
            return ""
        time.sleep(0.18)
        try:
            selected = pyperclip.paste() or ""
        except Exception:
            selected = ""
        try:
            pyperclip.copy(old or "")
        except Exception:
            pass
        return selected.strip()

def transcribe_with_fallback(audio):
    online = cfg.get("modo") == "online" and _cloud_key()
    if online:
        try:
            return transcribe_groq(audio)
        except Exception as e:
            log("Groq falló, reintentando con modelo offline:", repr(e))
            notify("Falló la conexión online. Reintentando automáticamente con el modelo offline…")
            return transcribe_local(audio)
    return transcribe_local(audio)

def can_retry_last():
    ap = last_recording.get("audio")
    return bool(ap and os.path.exists(ap))

def process(audio):
    kind = session_kind
    tone = session_tone or "mantener"
    try:
        if abort.is_set():
            return
        if len(audio) < FS * 0.3:
            set_state("listo", "corto")
            return
        audio_path = save_recording_audio(audio)
        secs = len(audio) / FS
        last_recording.update(audio=audio_path, kind=kind, tone=tone, ts=None, seconds=secs)
        proc_tip = kind if kind in ("comando", "escribir") else (tone if tone != "mantener" else "")
        set_state("procesando", proc_tip)
        selected = ""
        if kind == "comando":
            selected = grab_selection()
            if not selected:
                notify("Primero seleccioná el texto. Después usá el atajo de comando y decí qué hacer.")
                set_state("listo", "vacio")
                return
        raw = transcribe_with_fallback(audio)
        if abort.is_set():
            return
        if not (raw or "").strip():
            set_state("listo", "vacio")
            return
        raw = apply_dictionary(raw.strip())
        if kind == "dictado":
            direct = exact_snippet(raw)
            if direct:
                text = direct
            else:
                shaped = shape_text(raw, kind, selected, tone)
                if not shaped or is_ai_refusal_or_error(shaped, raw):
                    shaped = raw
                text = apply_snippets(apply_dictionary(shaped))
        else:
            text = shape_text(raw, kind, selected, tone)
            if not text or is_ai_refusal_or_error(text, raw):
                text = raw
        if abort.is_set():
            return
        if text:
            paste(text)
            try:
                ts = remember(text, secs, audio_path=audio_path)
                last_recording["ts"] = ts
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

def retry_transcription(audio_path=None, hist_ts=None, paste_result=True):
    path = audio_path or last_recording.get("audio")
    if not path or not os.path.exists(path):
        notify("El audio de esta grabación ya no está disponible.")
        return
    if recording or state_name == "procesando":
        return

    def worker():
        abort.clear()
        try:
            audio = load_recording_audio(path)
            if audio is None or len(audio) < FS * 0.3:
                notify("No pude leer el audio guardado.")
                return
            tone = last_recording.get("tone") or tone_now()
            set_state("procesando", "reintentando")
            raw = transcribe_with_fallback(audio)
            if abort.is_set():
                return
            if not (raw or "").strip():
                notify("No se detectó voz al reintentar.")
                set_state("listo", "vacio")
                return
            raw = apply_dictionary(raw.strip())
            direct = exact_snippet(raw)
            if direct:
                text = direct
            else:
                shaped = shape_text(raw, "dictado", "", tone)
                if not shaped or is_ai_refusal_or_error(shaped, raw):
                    shaped = raw
                text = apply_snippets(apply_dictionary(shaped))
            if abort.is_set() or not text:
                set_state("listo", "vacio")
                return
            target_ts = hist_ts if hist_ts is not None else last_recording.get("ts")
            new_ts = update_history_text(target_ts, text, seconds=len(audio) / FS, audio_path=path)
            if hist_ts is None:
                last_recording["ts"] = new_ts
            if paste_result:
                paste(text, watch=False)
            else:
                try:
                    pyperclip.copy(text)
                except Exception:
                    pass
            set_state("listo", "listo")
        except Exception as e:
            log("reintentar:", repr(e))
            beep("err")
            notify(human_error(e))
            set_state("listo", "error")

    threading.Thread(target=worker, daemon=True).start()

def _text_words(text):
    return re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text or "")

def one_word_change(before, after):
    bw, aw = _text_words(before), _text_words(after)
    if not bw or not aw:
        return None
    i = 0
    while i < len(bw) and i < len(aw) and bw[i] == aw[i]:
        i += 1
    j = 0
    while j < (len(bw) - i) and j < (len(aw) - i) and bw[-1 - j] == aw[-1 - j]:
        j += 1
    old = bw[i:len(bw) - j if j else len(bw)]
    new = aw[i:len(aw) - j if j else len(aw)]
    if len(old) == 1 and len(new) == 1 and old[0] != new[0]:
        return old[0], new[0]
    return None

def correction_pair(pasted, before, after):
    change = one_word_change(before, after)
    if not change:
        return None
    old, new = change
    if len(old) < 2 or len(new) < 2 or len(old) > 40 or len(new) > 40:
        return None
    if not re.search(_word_pat(old), pasted or ""):
        return None
    return old, new

def _known_correction(old, new):
    for entry in cfg.get("diccionario") or []:
        heard = (entry.get("oye") or "").strip()
        write = (entry.get("escribe") or "").strip()
        if heard.lower() == old.lower() and write == new:
            return True
    return False

def add_dictionary_correction(oye, escribe):
    items = [dict(e) for e in (cfg.get("diccionario") or [])]
    placed = False
    for entry in items:
        write = (entry.get("escribe") or "").strip()
        heard = (entry.get("oye") or "").strip()
        if heard.lower() == oye.lower() or (write.lower() == escribe.lower() and (not heard or heard.lower() == oye.lower())):
            entry["escribe"] = escribe
            entry["oye"] = oye
            if entry.get("tipo") not in ("nombre", "sigla", "jerga"):
                entry["tipo"] = "nombre" if escribe[:1].isupper() else "jerga"
            placed = True
            break
    if not placed:
        items.append({
            "escribe": escribe, "oye": oye,
            "tipo": "nombre" if escribe[:1].isupper() else "jerga",
        })
    cfg["diccionario"] = _clean_dict_entries(items)
    save()
    if controller is not None and getattr(controller, "settings", None) is not None:
        try:
            controller.settings.note_learned(oye, escribe)
        except Exception as e:
            log("diccionario", repr(e))

def _offer_correction(old, new):
    if not old or not new or _known_correction(old, new):
        return
    if bridge is not None:
        bridge.learn_offer.emit(old, new)

def _focused_control_text():
    if os.name != "nt":
        return None, "", False
    try:
        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                ("rcCaret", RECT),
            ]

        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.GetGUIThreadInfo.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        user32.GetGUIThreadInfo.restype = ctypes.c_bool
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_wchar_p]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        hwnd = user32.GetForegroundWindow()
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
            return None, "", False
        target = info.hwndFocus or hwnd
        n = int(user32.SendMessageW(target, 0x000E, 0, None) or 0)
        if n <= 0 or n > 20000:
            return target, "", False
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.SendMessageW(target, 0x000D, n + 1, buf)
        return target, buf.value or "", True
    except Exception as e:
        log("texto", repr(e))
        return None, "", False

def _watch_windows_text(pasted, gen):
    target, before, readable = _focused_control_text()
    if not readable or pasted.strip() not in (before or ""):
        return None, False
    deadline = time.time() + 8
    last, stable = before, None
    while time.time() < deadline and gen == learn_gen:
        time.sleep(0.35)
        now_target, text, still = _focused_control_text()
        if not still or now_target != target:
            break
        if text != last:
            last, stable = text, time.time()
        elif stable and text != before and time.time() - stable > 1.1:
            break
    if last == before:
        return None, True
    return correction_pair(pasted, before, last), True

def _watch_keys(pasted, gen, box):
    shadow = {"text": pasted, "ok": True, "mods": 0}
    original = pasted
    blocking = {"ctrl", "alt", "windows", "left windows", "right windows", "right ctrl", "left ctrl", "right alt", "left alt"}

    def handler(event):
        if gen != learn_gen:
            return
        name = event.name or ""
        if name in blocking or name in ("shift", "right shift", "left shift"):
            if name in blocking:
                if event.event_type == "down":
                    shadow["mods"] += 1
                elif shadow["mods"]:
                    shadow["mods"] -= 1
            return
        if box.get("stop") or not shadow["ok"] or event.event_type != "down":
            return
        if shadow["mods"]:
            shadow["ok"] = False
            return
        if name in ("backspace",):
            shadow["text"] = shadow["text"][:-1]
        elif name in ("space", "spacebar"):
            shadow["text"] += " "
        elif name == "enter":
            shadow["text"] += "\n"
        elif len(name) == 1:
            shadow["text"] += name
        else:
            shadow["ok"] = False

    try:
        hook = keyboard.hook(handler, suppress=False)
    except Exception as e:
        log("aprender", repr(e))
        return
    try:
        end = time.time() + 8
        last, stable = shadow["text"], None
        while time.time() < end and not box.get("stop") and shadow["ok"] and gen == learn_gen:
            time.sleep(0.2)
            cur = shadow["text"]
            if cur != last:
                last, stable = cur, time.time()
            elif stable and cur != original and time.time() - stable > 1.0:
                break
        if shadow["ok"] and shadow["text"] != original and gen == learn_gen:
            box["pair"] = correction_pair(original, original, shadow["text"])
    finally:
        try:
            keyboard.unhook(hook)
        except Exception:
            pass

def watch_correction(pasted, gen):
    try:
        if not cfg.get("aprender", True) or gen != learn_gen:
            return
        time.sleep(0.35)
        if gen != learn_gen:
            return
        box = {"stop": False, "pair": None}
        threading.Thread(target=_watch_keys, args=(pasted, gen, box), daemon=True).start()
        pair, readable = (None, False)
        if os.name == "nt":
            pair, readable = _watch_windows_text(pasted, gen)
        box["stop"] = True
        time.sleep(0.3)
        if gen != learn_gen:
            return
        if pair:
            _offer_correction(*pair)
        elif not readable and box.get("pair"):
            _offer_correction(*box["pair"])
    except Exception as e:
        log("aprender", repr(e))

def paste(text, watch=True):
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
    if watch and cfg.get("aprender", True) and (text or "").strip():
        inserted = text if text.endswith((" ", "\n")) else text + " "
        threading.Thread(target=watch_correction, args=(inserted, learn_gen), daemon=True).start()

def push_level(chunk):
    v = chunk_level(chunk)
    if v < 0.05:
        v = 0.06
    with level_lock:
        prev = levels[-1]
        levels.pop(0)
        levels.append(prev * 0.18 + v * 0.82)

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
    global recording, frames, stream, learn_gen
    if recording or capturing:
        return
    with mic_lock:
        if recording:
            return
        if controller is not None:
            controller._stop_monitor()
        learn_gen += 1
        abort.clear()
        with level_lock:
            for i in range(len(levels)):
                levels[i] = 0.06
        frames = []
        recording = True
        beep("start")
        set_state("grabando", {"comando": "comando", "escribir": "escribir"}.get(session_kind, ""))
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

def _combo_held(combo):
    combo = (combo or "").strip().lower()
    if not combo:
        return False
    try:
        return bool(keyboard.is_pressed(combo))
    except Exception:
        return False

def _most_specific_kind():
    best = None
    for kind, key in (("dictado", "atajo"), ("comando", "atajo_cmd"), ("escribir", "atajo_escribir")):
        combo = (cfg.get(key) or "").strip().lower()
        if combo and _combo_held(combo):
            score = len(combo.split("+"))
            if best is None or score > best[0]:
                best = (score, kind)
    return best[1] if best else None

def on_hotkey(kind="dictado"):
    global session_kind, session_tone
    if capturing or state_name == "procesando":
        return
    specific = _most_specific_kind()
    if specific and specific != kind:
        return
    if recording:
        if cfg.get("modo_tecla") == "alternar" and session_kind == kind:
            stop_rec()
        return
    session_kind = kind
    session_tone = tone_now()
    start_rec()
    if cfg.get("modo_tecla") == "alternar":
        return
    keyname = {"dictado": "atajo", "comando": "atajo_cmd", "escribir": "atajo_escribir"}.get(kind, "atajo")
    key = (cfg.get(keyname) or "").strip().lower()

    def waiter():
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

def _unhook_hotkeys():
    global hk, hotkeys
    for h in list(hotkeys.values()):
        try:
            keyboard.remove_hotkey(h)
        except Exception:
            pass
    try:
        if hk:
            keyboard.remove_hotkey(hk)
    except Exception:
        pass
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass
    hk = None
    hotkeys = {}

def register_hotkey(announce=True):
    global hk, hotkeys
    _unhook_hotkeys()
    specs = [
        ("atajo", "ctrl+alt+space", "dictado"),
        ("atajo_cmd", "ctrl+alt+shift+space", "comando"),
        ("atajo_escribir", "ctrl+alt+a", "escribir"),
    ]
    changed = False
    for key, fallback, kind in specs:
        combo = (cfg.get(key) or fallback).strip().lower()
        try:
            hotkeys[key] = keyboard.add_hotkey(combo, lambda k=kind: on_hotkey(k), suppress=False, trigger_on_release=False)
        except Exception as e:
            log("atajo", key, repr(e))
            if combo != fallback:
                cfg[key] = fallback
                changed = True
                try:
                    hotkeys[key] = keyboard.add_hotkey(fallback, lambda k=kind: on_hotkey(k), suppress=False, trigger_on_release=False)
                    if announce:
                        notify(f"Un atajo no funcionaba. Volví a {pretty_hotkey(fallback)}.")
                except Exception as e2:
                    log("atajo fallback", key, repr(e2))
    if "atajo" in hotkeys:
        hk = hotkeys["atajo"]
    if changed:
        save()
    ok = "atajo" in hotkeys
    if not ok and announce:
        notify("No pude activar el atajo. Abrí Configuración y elegí otro.")
    return ok

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
            winreg.SetValueEx(k, "DictadoLibre", 0, winreg.REG_SZ, f'"{sys.executable}" --tray')
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
QWidget#settings { background: #0b0d13; color: #f2f4f8; }
QLabel { background: transparent; color: #f2f4f8; border: none; }
QLabel#muted { color: #949ab0; font-size: 12px; border: none; }
QLabel#h1 { font-size: 24px; font-weight: 700; color: #ffffff; border: none; }
QLabel#secTitle { font-size: 13px; font-weight: 700; color: #a78bfa; letter-spacing: 0.4px; border: none; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; color: #f2f4f8; border: none; }
QLabel#hotkey {
    background: #121521;
    color: #e9e5ff;
    border: 1px solid #353b54;
    border-bottom: 2px solid #4a5170;
    border-radius: 10px;
    padding: 6px 12px;
    font-size: 14px;
    font-weight: 700;
}
QLabel#metric { font-size: 28px; font-weight: 700; color: #ffffff; border: none; }
QLabel#brand { font-size: 16px; font-weight: 700; color: #ffffff; border: none; }
QLabel#autosave {
    background: #14241f;
    color: #3dd68c;
    border: 1px solid #214337;
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
}
QFrame#side { background: #10131c; border-right: 1px solid #1e2231; }
QFrame#card { background: #151824; border: 1px solid #23283b; border-radius: 14px; }
QFrame#cardOn { background: #1d1a33; border: 1.5px solid #7c6af7; border-radius: 14px; }
QFrame#subcard { background: #10131d; border: 1px solid #1f2436; border-radius: 11px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QPushButton {
    border: 1px solid #2b3044;
    border-radius: 10px;
    padding: 7px 14px;
    background: #1e2231;
    color: #eef0f6;
    font-weight: 500;
}
QPushButton:hover { background: #282d40; border-color: #3a415a; }
QPushButton#primary { background: #7c6af7; border: 1px solid #8e7ff9; color: white; font-weight: 600; padding: 8px 16px; }
QPushButton#primary:hover { background: #8d7cff; }
QPushButton#ghost { background: #191d2b; border: 1px solid #282e42; color: #d5d8e6; }
QPushButton#ghost:hover { background: #23283b; color: white; }
QPushButton#nav {
    background: transparent;
    border: 1px solid transparent;
    color: #9ea4b8;
    text-align: left;
    padding: 10px 12px;
    border-radius: 11px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton#nav:hover { background: #171b28; color: #eef0f6; }
QPushButton#nav:checked {
    background: #211e38;
    border: 1px solid #483d8b;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#danger { background: #261922; border: 1px solid #422332; color: #ff8b9a; }
QPushButton#danger:hover { background: #361e2c; }
QPushButton#chip { background: #1d2130; border: 1px solid #2b3147; color: #e4e7f2; border-radius: 9px; padding: 5px 11px; font-size: 12px; }
QPushButton#chip:hover { background: #272c40; border-color: #3d4563; }
QLineEdit, QComboBox, QPlainTextEdit {
    background: #0f121b;
    color: #f2f4f8;
    border: 1px solid #282e42;
    border-radius: 10px;
    padding: 7px 11px;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #7c6af7; background: #121521; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: #161925; color: #f2f4f8; selection-background-color: #7c6af7; border: 1px solid #2e344b; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #343a4f; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #48506b; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }
"""

def nav_icon(kind, active=False):
    pm = QPixmap(20, 20)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor("#a78bfa" if active else "#8e95ab")
    pen = QPen(col, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if kind == "home":
        p.drawRoundedRect(QRectF(3, 3, 6, 6), 1.5, 1.5)
        p.drawRoundedRect(QRectF(11, 3, 6, 6), 1.5, 1.5)
        p.drawRoundedRect(QRectF(3, 11, 6, 6), 1.5, 1.5)
        p.drawRoundedRect(QRectF(11, 11, 6, 6), 1.5, 1.5)
    elif kind == "mic":
        p.drawRoundedRect(QRectF(7, 2.5, 6, 9.5), 3, 3)
        p.drawArc(QRectF(4.5, 6.5, 11, 8.5), 180 * 16, 180 * 16)
        p.drawLine(QPointF(10, 15), QPointF(10, 17.5))
        p.drawLine(QPointF(7, 17.5), QPointF(13, 17.5))
    elif kind == "kbd":
        p.drawRoundedRect(QRectF(2.5, 4.5, 15, 11), 2.2, 2.2)
        for x in (6, 10, 14):
            p.drawPoint(QPointF(x, 8))
        p.drawLine(QPointF(6.5, 12), QPointF(13.5, 12))
    elif kind == "book":
        p.drawRoundedRect(QRectF(4, 3, 12, 14), 2, 2)
        p.drawLine(QPointF(7.5, 7), QPointF(12.5, 7))
        p.drawLine(QPointF(7.5, 10.5), QPointF(12.5, 10.5))
        p.drawLine(QPointF(7.5, 14), QPointF(10.5, 14))
    p.end()
    return QIcon(pm)

class Bridge(QObject):
    state_changed = Signal(str, str)
    notice = Signal(str)
    update_ready = Signal()
    history_changed = Signal()
    mic_level = Signal(float)
    learn_offer = Signal(str, str)

class Pill(QWidget):
    def __init__(self):
        super().__init__()
        self.state = "listo"
        self.tip = ""
        self._phase = 0.0
        self._token = 0
        self._hover_x = False
        self._hover_retry = False
        self._cancel = QRectF()
        self._retry = QRectF()
        self._drag_start_global = None
        self._drag_origin = None
        self._dragging = False
        self.setFixedSize(104, 34)
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
        px, py = cfg.get("pill_x"), cfg.get("pill_y")
        if isinstance(px, int) and isinstance(py, int):
            x = max(geo.left() + 4, min(px, geo.right() - self.width() - 4))
            y = max(geo.top() + 4, min(py, geo.bottom() - self.height() - 4))
            self.move(x, y)
        else:
            self.move(geo.x() + (geo.width() - self.width()) // 2, geo.y() + geo.height() - 10 - self.height())

    def reset_position(self):
        cfg["pill_x"] = None
        cfg["pill_y"] = None
        save(cfg)
        self.place()

    def _tick(self):
        if self.isVisible():
            self._phase += 0.22
            self.update()

    def _can_show_retry(self):
        return self.state == "listo" and self.tip in ("listo", "vacio", "error") and can_retry_last()

    def on_state(self, state, tip):
        self.state = state
        self.tip = tip or ""
        self._token += 1
        token = self._token
        self._hover_x = False
        self._hover_retry = False
        title, hint = self._copy()
        extra = " · Clic en ↻ para reintentar transcripción" if self._can_show_retry() else ""
        drag_hint = " · Arrastrá para mover (doble clic centra)"
        self.setToolTip(f"{title}. {hint}{extra}{drag_hint}".strip())
        if state in ("grabando", "procesando", "cargando"):
            if not self._dragging:
                self.place()
            self.show()
            self.raise_()
        elif tip in ("listo", "corto", "vacio", "error", "cancelado"):
            if not self._dragging:
                self.place()
            self.show()
            self.raise_()
            delay = 2800 if self._can_show_retry() else 1200
            QTimer.singleShot(delay, lambda t=token: self._hide_if(t))
        else:
            self.hide()
        self.update()

    def _hide_if(self, token):
        if token != self._token or self.state != "listo":
            return
        if self.underMouse() or self._dragging:
            QTimer.singleShot(900, lambda t=token: self._hide_if(t))
            return
        self.hide()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._dragging:
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
            hold = cfg.get("modo_tecla") != "alternar"
            if self.tip == "comando":
                return "Comando", "Soltá para aplicar" if hold else "Tocá para aplicar"
            if self.tip == "escribir":
                return "Ayuda", "Soltá para armar" if hold else "Tocá para armar"
            return "Escuchando", "Soltá para pegar" if hold else "Tocá de nuevo"
        if self.state == "procesando":
            if self.tip == "reintentando":
                return "Reintentando", "Transcribiendo de nuevo"
            if self.tip == "comando":
                return "Aplicando", "Un segundo"
            if self.tip == "escribir":
                return "Armando", "Un segundo"
            if self.tip == "formal":
                return "Procesando", "Tono formal"
            if self.tip == "mensaje":
                return "Procesando", "Tono chat"
            if self.tip == "tecnico":
                return "Procesando", "Tono técnico"
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
            if self.tip == "comando":
                return QColor("#a78bfa")  # Violeta: modo Comando
            if self.tip == "escribir":
                return QColor("#38bdf8")  # Celeste: modo Ayudame a escribir
            return QColor("#3dd68c")      # Verde: Dictado normal
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
            n = len(data)
            return [
                max(0.10, min(1.0, v * (0.58 + 0.42 * math.sin(math.pi * (i + 0.5) / n))))
                for i, v in enumerate(data)
            ]
        if self.state == "procesando":
            return [
                (0.14 + 0.16 * (0.5 + 0.5 * math.cos(self._phase * 1.5 - i * 0.48)))
                * (0.62 + 0.38 * math.sin(math.pi * (i + 0.5) / BAR_N))
                for i in range(BAR_N)
            ]
        if self.state == "cargando":
            return [
                (0.12 + 0.10 * (0.5 + 0.5 * math.cos(self._phase * 0.9 - i * 0.42)))
                * (0.62 + 0.38 * math.sin(math.pi * (i + 0.5) / BAR_N))
                for i in range(BAR_N)
            ]
        return [0.12 * (0.62 + 0.38 * math.sin(math.pi * (i + 0.5) / BAR_N)) for i in range(BAR_N)]

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        outer = QRectF(4, 4, self.width() - 8, self.height() - 8)
        radius = outer.height() / 2.0
        for i, alpha in ((3, 14), (1.5, 26)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(outer.adjusted(-i, i * 0.4, i, i + 0.8), radius + i * 0.5, radius + i * 0.5)
        bg = QLinearGradient(outer.topLeft(), outer.bottomLeft())
        bg.setColorAt(0.0, QColor(26, 28, 38, 232))
        bg.setColorAt(1.0, QColor(14, 15, 22, 240))
        dot = self._dot()
        border = QLinearGradient(outer.topLeft(), outer.bottomLeft())
        border.setColorAt(0.0, QColor(255, 255, 255, 44))
        border.setColorAt(1.0, QColor(dot.red(), dot.green(), dot.blue(), 42))
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(outer, radius, radius)

        cx, cy = outer.left() + 12, outer.center().y()
        glow_r = (6.2 + 1.8 * abs(math.sin(self._phase * 1.4))) if self.state in ("grabando", "procesando") else 5.0
        rg = QRadialGradient(QPointF(cx, cy), glow_r)
        rg.setColorAt(0.0, QColor(dot.red(), dot.green(), dot.blue(), 115))
        rg.setColorAt(0.55, QColor(dot.red(), dot.green(), dot.blue(), 38))
        rg.setColorAt(1.0, QColor(dot.red(), dot.green(), dot.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(rg)
        p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))
        p.setBrush(dot)
        p.drawEllipse(QRectF(cx - 2.6, cy - 2.6, 5.2, 5.2))
        p.setBrush(QColor(255, 255, 255, 145))
        p.drawEllipse(QRectF(cx - 1.2, cy - 1.3, 1.6, 1.6))

        show_x = self.state in ("grabando", "procesando")
        show_retry = self._can_show_retry()
        has_btn = show_x or show_retry
        bars = self._bars()
        left = outer.left() + 22
        right = outer.right() - (22 if has_btn else 10)
        gap = 2.0
        bw = max(1.8, (right - left - gap * (len(bars) - 1)) / len(bars))
        max_h = outer.height() - 8
        for i, v in enumerate(bars):
            h = max(2.6, max_h * v)
            x = left + i * (bw + gap)
            bar_rect = QRectF(x, cy - h / 2, bw, h)
            grad = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomLeft())
            if self.state == "grabando":
                alpha = int(160 + 95 * v)
                if self.tip == "comando":
                    grad.setColorAt(0.0, QColor(243, 232, 255, alpha))
                    grad.setColorAt(0.5, QColor(196, 181, 253, alpha))
                    grad.setColorAt(1.0, QColor(139, 92, 246, alpha))
                elif self.tip == "escribir":
                    grad.setColorAt(0.0, QColor(224, 242, 254, alpha))
                    grad.setColorAt(0.5, QColor(125, 211, 252, alpha))
                    grad.setColorAt(1.0, QColor(56, 189, 248, alpha))
                else:
                    grad.setColorAt(0.0, QColor(236, 253, 245, alpha))
                    grad.setColorAt(0.5, QColor(167, 243, 208, alpha))
                    grad.setColorAt(1.0, QColor(61, 214, 140, alpha))
            elif self.state in ("procesando", "cargando"):
                shimmer = 0.5 + 0.5 * math.cos(self._phase * 1.5 - i * 0.48)
                alpha = int(85 + 165 * shimmer)
                grad.setColorAt(0.0, QColor(244, 240, 255, alpha))
                grad.setColorAt(1.0, QColor(145, 128, 252, max(65, alpha - 25)))
            else:
                grad.setColorAt(0.0, QColor(186, 178, 224, 120))
                grad.setColorAt(1.0, QColor(124, 106, 247, 95))
            p.setBrush(grad)
            p.drawRoundedRect(bar_rect, bw / 2, bw / 2)

        btn_rect = QRectF(outer.right() - 16.5, cy - 6.5, 13, 13)
        self._cancel = btn_rect if show_x else QRectF()
        self._retry = btn_rect if show_retry else QRectF()
        if show_x:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 77, 106, 65) if self._hover_x else QColor(255, 255, 255, 16))
            p.drawEllipse(self._cancel)
            p.setPen(QPen(QColor("#ffd6de" if self._hover_x else "#c8ccd8"), 1.15, Qt.SolidLine, Qt.RoundCap))
            c = self._cancel.center()
            p.drawLine(QPointF(c.x() - 2.1, c.y() - 2.1), QPointF(c.x() + 2.1, c.y() + 2.1))
            p.drawLine(QPointF(c.x() + 2.1, c.y() - 2.1), QPointF(c.x() - 2.1, c.y() + 2.1))
        elif show_retry:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(124, 106, 247, 175) if self._hover_retry else QColor(255, 255, 255, 24))
            p.drawEllipse(self._retry)
            p.setPen(QPen(QColor("#ffffff" if self._hover_retry else "#dcdff0"), 1.2, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            arc_r = self._retry.adjusted(3.2, 3.2, -3.2, -3.2)
            p.drawArc(arc_r, 35 * 16, 275 * 16)
            c = self._retry.center()
            p.drawLine(QPointF(c.x() + 1.5, c.y() - 3.3), QPointF(c.x() + 3.4, c.y() - 1.7))
            p.drawLine(QPointF(c.x() + 3.4, c.y() - 1.7), QPointF(c.x() + 1.1, c.y() - 1.1))
        p.end()

    def mouseMoveEvent(self, e):
        if self._drag_start_global is not None and (e.buttons() & Qt.LeftButton):
            delta = e.globalPosition().toPoint() - self._drag_start_global
            if not self._dragging and delta.manhattanLength() > 4:
                self._dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                target = self._drag_origin + delta
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    x = max(geo.left() + 4, min(target.x(), geo.right() - self.width() - 4))
                    y = max(geo.top() + 4, min(target.y(), geo.bottom() - self.height() - 4))
                    self.move(x, y)
                else:
                    self.move(target)
                return
        pos = e.position()
        hx = self._cancel.contains(pos)
        hr = self._retry.contains(pos)
        if hx != self._hover_x or hr != self._hover_retry:
            self._hover_x = hx
            self._hover_retry = hr
            if hr:
                self.setToolTip("Reintentar transcripción")
            self.update()
        if hx or hr:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.reset_position()
            return
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self._cancel.contains(pos) and self.state in ("grabando", "procesando"):
            self._drag_start_global = None
            cancel_dictation()
            return
        if self._retry.contains(pos) and self._can_show_retry():
            self._drag_start_global = None
            retry_transcription()
            return
        self._drag_start_global = e.globalPosition().toPoint()
        self._drag_origin = self.pos()
        self._dragging = False

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        was_dragging = self._dragging
        had_press = self._drag_start_global is not None
        self._drag_start_global = None
        self._drag_origin = None
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)
        if was_dragging:
            cfg["pill_x"] = int(self.x())
            cfg["pill_y"] = int(self.y())
            save(cfg)
            return
        if had_press and self.state == "grabando":
            stop_rec()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start_global = None
            self._dragging = False
            self.reset_position()

class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False):
        super().__init__()
        self._on = bool(checked)
        self.setFixedSize(44, 24)
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
        p.setBrush(QColor("#7c6af7" if self._on else "#2c3142"))
        p.drawRoundedRect(0, 0, 44, 24, 12, 12)
        p.setBrush(QColor("white"))
        p.drawEllipse(22 if self._on else 3, 3, 18, 18)
        p.end()

class LevelBar(QWidget):
    def __init__(self):
        super().__init__()
        self.level = 0.0
        self.setFixedHeight(10)

    def set_level(self, v):
        self.level = max(0.0, min(1.0, float(v)))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#222738"))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 5, 5)
        w = self.width() * self.level
        if w > 0:
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0.0, QColor("#3dd68c"))
            grad.setColorAt(0.7, QColor("#7c6af7"))
            grad.setColorAt(1.0, QColor("#a78bfa"))
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(0, 0, w, self.height()), 5, 5)
        p.end()

def button(text, kind="ghost"):
    b = QPushButton(text)
    b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(34 if kind != "primary" else 38)
    return b

def card(kind="card"):
    f = QFrame()
    f.setObjectName(kind)
    f.setAttribute(Qt.WA_StyledBackground, True)
    f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return f

def section_label(text):
    lab = QLabel(text)
    lab.setObjectName("secTitle")
    return lab

def card_title(text):
    lab = QLabel(text)
    lab.setObjectName("cardTitle")
    lab.setWordWrap(True)
    return lab

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
    t = card_title(title)
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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 13, 16, 13)
        lay.setSpacing(4)
        self.title = card_title(title)
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
    combo.setMinimumHeight(36)
    view = combo.view()
    view.setStyleSheet("background:#161925; color:#f2f4f8; selection-background-color:#7c6af7; selection-color:white; padding:4px;")

def fill_combo(combo, pairs, current):
    combo.clear()
    for value, label in pairs:
        combo.addItem(label, value)
    if current and combo.findData(current) < 0:
        combo.addItem(str(current), current)
    i = combo.findData(current)
    combo.setCurrentIndex(i if i >= 0 else 0)

NAV_ITEMS = [
    ("home", "Inicio"),
    ("mic", "Voz y Micrófono"),
    ("kbd", "Escritura y Atajos"),
    ("book", "Vocabulario"),
]

class Settings(QWidget):
    def __init__(self):
        super().__init__()
        self._initializing = True
        self.setObjectName("settings")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(APP)
        self.setStyleSheet(SETTINGS_QSS)
        self.setMinimumSize(900, 620)
        self.resize(980, 680)
        self.hotkey = cfg.get("atajo") or "ctrl+alt+space"
        self.hotkey_cmd = cfg.get("atajo_cmd") or "ctrl+alt+shift+space"
        self.hotkey_write = cfg.get("atajo_escribir") or "ctrl+alt+a"
        self.modo = cfg.get("modo") or "local"
        self.tecla = cfg.get("modo_tecla") or "mantener"
        self._cap_target = "atajo"
        self._capturing = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._auto_save)
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
        self.stack.addWidget(scroller(self._page_home()))
        self.stack.addWidget(scroller(self._page_voice_mic()))
        self.stack.addWidget(scroller(self._page_write_shortcuts()))
        self.stack.addWidget(scroller(self._page_words()))
        right.addWidget(self.stack, 1)
        wrap = QWidget()
        wrap.setLayout(right)
        root.addWidget(wrap, 1)
        self.stack.currentChanged.connect(self._on_page)
        self._select_nav(0)
        if bridge is not None:
            bridge.history_changed.connect(self._refresh_lists)
            bridge.update_ready.connect(self._refresh_update)
            bridge.mic_level.connect(self.level.set_level)
        self._initializing = False

    def _sidebar(self):
        side = QFrame()
        side.setObjectName("side")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(232)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(6)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(brand_pixmap(34))
        logo.setFixedSize(34, 34)
        col_b = QVBoxLayout()
        col_b.setSpacing(1)
        name = QLabel(APP)
        name.setObjectName("brand")
        ver = muted(f"Versión {VERSION}")
        col_b.addWidget(name)
        col_b.addWidget(ver)
        brand.addWidget(logo)
        brand.addSpacing(6)
        brand.addLayout(col_b, 1)
        lay.addLayout(brand)
        lay.addSpacing(14)
        self.nav = []
        for i, (icon_kind, text) in enumerate(NAV_ITEMS):
            b = button("  " + text, "nav")
            b.setIcon(nav_icon(icon_kind, active=False))
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=i: self.open_page(n))
            self.nav.append((icon_kind, b))
            lay.addWidget(b)
        lay.addStretch(1)
        self.footer_msg = QLabel("✓ Guardado automático")
        self.footer_msg.setObjectName("autosave")
        self.footer_msg.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.footer_msg)
        lay.addSpacing(4)
        self.update_btn = button("Buscar actualizaciones", "ghost")
        self.update_btn.clicked.connect(self._update_click)
        lay.addWidget(self.update_btn)
        self.update_hint = muted("Estás al día.")
        self.update_hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.update_hint)
        return side

    def _schedule_save(self):
        if getattr(self, "_initializing", False):
            return
        self._save_timer.start(220)

    def _flash_saved(self, text="✓ Guardado en vivo"):
        self.footer_msg.setText(text)
        QTimer.singleShot(2000, lambda: self.footer_msg.setText("✓ Guardado automático"))

    def _page_shell(self, title, subtitle):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        hdr = QVBoxLayout()
        hdr.setSpacing(3)
        h = QLabel(title)
        h.setObjectName("h1")
        hdr.addWidget(h)
        hdr.addWidget(muted(subtitle))
        lay.addLayout(hdr)
        return page, lay

    # ---------- 0. INICIO (Métricas + Caja de prueba rápida + Historial con buscador) ----------
    def _page_home(self):
        page, lay = self._page_shell(
            "Inicio",
            "Tus estadísticas de velocidad, un área para probar el dictado ahora mismo y tus últimos textos.")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.m_words, self.m_words_n = self._metric("0", "Palabras dictadas")
        self.m_wpm, self.m_wpm_n = self._metric("0", "Palabras por minuto")
        self.m_saved, self.m_saved_n = self._metric("0 s", "Tiempo ahorrado")
        row.addWidget(self.m_words, 1)
        row.addWidget(self.m_wpm, 1)
        row.addWidget(self.m_saved, 1)
        lay.addLayout(row)
        self.last_label = muted("Todavía no hay dictados.")
        lay.addWidget(self.last_label)

        # Caja de prueba rápida
        play = card()
        pl = QVBoxLayout(play)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(8)
        top_p = QHBoxLayout()
        top_p.addWidget(card_title("Caja de prueba rápida"), 1)
        copy_p = button("Copiar", "chip")
        clear_p = button("Limpiar", "chip")
        top_p.addWidget(copy_p)
        top_p.addWidget(clear_p)
        pl.addLayout(top_p)
        self.playground = QPlainTextEdit()
        self.playground.setFixedHeight(84)
        self._sync_playground_placeholder()
        copy_p.clicked.connect(lambda: self._copy_text(self.playground.toPlainText(), copy_p))
        clear_p.clicked.connect(self.playground.clear)
        pl.addWidget(self.playground)
        pl.addWidget(muted("Hacé clic adentro del cuadro, mantené tu atajo y hablá (en español, inglés o ambos) para probar sin salir de acá."))
        lay.addWidget(play)

        # Historial reciente con buscador
        hist_hdr = QHBoxLayout()
        hist_hdr.addWidget(section_label("HISTORIAL RECIENTE"), 1)
        self.hist_search = QLineEdit()
        self.hist_search.setPlaceholderText("Buscar en el historial…")
        self.hist_search.setFixedWidth(220)
        self.hist_search.textChanged.connect(lambda *_: self._refresh_history())
        wipe = button("Borrar todo", "danger")
        wipe.clicked.connect(self._wipe_history)
        hist_hdr.addWidget(self.hist_search)
        hist_hdr.addWidget(wipe)
        lay.addLayout(hist_hdr)

        self.hist_box = QVBoxLayout()
        self.hist_box.setSpacing(8)
        lay.addLayout(self.hist_box)
        lay.addStretch(1)
        self._refresh_stats()
        self._refresh_history()
        return page

    def _sync_playground_placeholder(self):
        if hasattr(self, "playground"):
            hk_txt = pretty_hotkey(cfg.get("atajo") or self.hotkey or "ctrl+alt+space")
            self.playground.setPlaceholderText(f"Hacé clic acá, mantené apretado {hk_txt} y hablá para probar…")

    # ---------- 1. VOZ Y MICRÓFONO ----------
    def _page_voice_mic(self):
        page, lay = self._page_shell(
            "Voz y Micrófono",
            "Probá tu micrófono en vivo, elegí el idioma (Español, Inglés o Multilingüe) y el motor de transcripción.")
        lay.addWidget(section_label("MICRÓFONO EN VIVO"))
        mic_card = card()
        ml = QVBoxLayout(mic_card)
        ml.setContentsMargins(16, 14, 16, 14)
        ml.setSpacing(10)
        mrow = QHBoxLayout()
        mrow.setSpacing(10)
        self.mic = QComboBox()
        polish_combo(self.mic)
        self._fill_mics()
        ref = button("Actualizar lista", "ghost")
        ref.clicked.connect(self._fill_mics)
        mrow.addWidget(self.mic, 1)
        mrow.addWidget(ref)
        ml.addLayout(mrow)
        self.level = LevelBar()
        ml.addWidget(self.level)
        self.mic_msg = muted("Hablá ahora: si la barra se mueve, el micrófono está recibiendo tu voz.")
        ml.addWidget(self.mic_msg)
        lay.addWidget(mic_card)

        self.sw_sus = Switch(bool(cfg.get("susurro")))
        self.sw_sus.toggled.connect(lambda *_: self._auto_save())
        lay.addWidget(switch_row(
            "Modo susurro",
            "Amplifica la voz cuando hablás bajito para que no se corten las frases suaves.",
            self.sw_sus))
        self.mic.currentIndexChanged.connect(lambda *_: (self._mic_changed(), self._auto_save()))

        lay.addWidget(section_label("IDIOMA Y MOTOR DE VOZ"))
        lang_card = card()
        ll = QVBoxLayout(lang_card)
        ll.setContentsMargins(16, 14, 16, 14)
        ll.setSpacing(8)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        left_c, right_c = QVBoxLayout(), QVBoxLayout()
        left_c.setSpacing(5)
        right_c.setSpacing(5)
        left_c.addWidget(card_title("Idioma de dictado"))
        self.lang = QComboBox()
        polish_combo(self.lang)
        fill_combo(self.lang, LANGS, cfg.get("idioma") or "es")
        self.lang.currentIndexChanged.connect(lambda *_: self._auto_save())
        left_c.addWidget(self.lang)
        right_c.addWidget(card_title("Calidad en esta computadora"))
        self.model = QComboBox()
        polish_combo(self.model)
        fill_combo(self.model, MODELS, cfg.get("modelo") or "small")
        self.model.currentIndexChanged.connect(lambda *_: (self._model_hint(), self._auto_save()))
        right_c.addWidget(self.model)
        cols.addLayout(left_c, 1)
        cols.addLayout(right_c, 1)
        ll.addLayout(cols)
        self.model_hint = muted(MODEL_HINT.get(cfg.get("modelo") or "small", ""))
        ll.addWidget(self.model_hint)
        lay.addWidget(lang_card)

        row_m = QHBoxLayout()
        row_m.setSpacing(12)
        self.card_local = Choice("En esta computadora", "100% privado y offline. Usa el modelo descargado en tu equipo.")
        self.card_online = Choice("Por internet, con Groq", "Ultrarrápido y preciso. Si se corta internet, pasa solo al modo local.")
        self.card_local.clicked = lambda: (self._set_modo("local"), self._auto_save())
        self.card_online.clicked = lambda: (self._set_modo("online"), self._auto_save())
        row_m.addWidget(self.card_local, 1)
        row_m.addWidget(self.card_online, 1)
        lay.addLayout(row_m)

        self.groq_box = card()
        bl = QVBoxLayout(self.groq_box)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(8)
        bl.addWidget(card_title("Clave de Groq (gratis)"))
        self.key = QLineEdit(cfg.get("groq_key", ""))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Pegá acá tu clave gsk_...")
        self.key.textChanged.connect(lambda *_: self._schedule_save())
        bl.addWidget(self.key)
        tools = QHBoxLayout()
        link = button("Conseguir clave gratis en Groq", "ghost")
        link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://console.groq.com/keys")))
        self.sw_show = Switch(False)
        self.sw_show.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        show_row = QHBoxLayout()
        show_row.addWidget(muted("Mostrar"))
        show_row.addWidget(self.sw_show)
        tools.addWidget(link, 0, Qt.AlignLeft)
        tools.addStretch(1)
        tools.addLayout(show_row)
        bl.addLayout(tools)
        self.groq_hint = muted("La clave también mejora el pulido de texto, Comando y Ayudame a escribir.")
        bl.addWidget(self.groq_hint)
        lay.addWidget(self.groq_box)
        self._set_modo(self.modo)
        lay.addStretch(1)
        return page

    # ---------- 2. ESCRITURA Y ATAJOS ----------
    def _page_write_shortcuts(self):
        page, lay = self._page_shell(
            "Escritura y Atajos",
            "Configurá tus atajos de teclado en vivo, el modo de pulsación y cómo se adapta el tono a cada programa.")
        lay.addWidget(section_label("ATAJOS DE TECLADO (SE APLICAN EN VIVO)"))
        hk_grid = QHBoxLayout()
        hk_grid.setSpacing(10)
        hk_grid.addWidget(self._hotkey_card(
            "Dictado normal",
            "Punto verde en la cápsula. Dicta donde está el cursor.",
            "atajo", "hotkey"), 1)
        hk_grid.addWidget(self._hotkey_card(
            "Modo Comando",
            "Punto violeta. Transforma el texto seleccionado.",
            "cmd", "hotkey_cmd"), 1)
        hk_grid.addWidget(self._hotkey_card(
            "Ayudame a escribir",
            "Punto celeste. Dictás la idea y redacta el mensaje.",
            "escribir", "hotkey_write"), 1)
        lay.addLayout(hk_grid)

        row_t = QHBoxLayout()
        row_t.setSpacing(12)
        self.card_hold = Choice("Mantener apretado", "Hablás mientras mantenés las teclas apretadas y escribe al soltar.")
        self.card_toggle = Choice("Un toque", "Un toque empieza a escuchar y otro toque pega el texto.")
        self.card_hold.clicked = lambda: (self._set_tecla("mantener"), self._auto_save())
        self.card_toggle.clicked = lambda: (self._set_tecla("alternar"), self._auto_save())
        row_t.addWidget(self.card_hold, 1)
        row_t.addWidget(self.card_toggle, 1)
        lay.addLayout(row_t)
        self._set_tecla(self.tecla)

        lay.addWidget(section_label("ESTILO E INTELIGENCIA"))
        self.sw_pulir = Switch(cfg.get("pulir", True))
        self.sw_pulir.toggled.connect(lambda *_: self._auto_save())
        lay.addWidget(switch_row(
            "Pulir el texto automáticamente",
            "Limpia muletillas, aplica autocorrecciones al vuelo y arma listas o párrafos.",
            self.sw_pulir))

        tone_card = card()
        tl = QVBoxLayout(tone_card)
        tl.setContentsMargins(16, 14, 16, 14)
        tl.setSpacing(8)
        t_top = QHBoxLayout()
        t_top.addWidget(card_title("Tono general"), 1)
        self.tone_combo = QComboBox()
        polish_combo(self.tone_combo)
        fill_combo(self.tone_combo, TONE_ALL, cfg.get("tono") or "auto")
        self.tone_combo.setMinimumWidth(220)
        self.tone_combo.currentIndexChanged.connect(lambda *_: self._auto_save())
        t_top.addWidget(self.tone_combo)
        tl.addLayout(t_top)
        tl.addWidget(muted("«Según la aplicación» usa tono formal en correo/Word, chat en WhatsApp/Slack y técnico en editores de código."))
        lay.addWidget(tone_card)

        self.sw_en = Switch(bool(cfg.get("traducir_en")))
        self.sw_en.toggled.connect(lambda *_: self._auto_save())
        lay.addWidget(switch_row(
            "Traducir salida al inglés",
            "Aunque hables en español, redacta el resultado final en inglés (requiere clave de Groq).",
            self.sw_en))

        apps = card()
        al = QVBoxLayout(apps)
        al.setContentsMargins(16, 14, 16, 14)
        al.setSpacing(8)
        al.addWidget(card_title("Tono específico por aplicación"))
        al.addWidget(muted("Elegí qué tono aplica automáticamente cuando dictás dentro de cada programa."))
        self.tone_box = QVBoxLayout()
        self.tone_box.setSpacing(6)
        al.addLayout(self.tone_box)
        self._tone_widgets = []
        saved = {str(k).lower(): v for k, v in (cfg.get("tonos") or {}).items()} if isinstance(cfg.get("tonos"), dict) else {}
        for exe, tone, _name in APP_RULES:
            self._add_tone_row(exe, saved.get(exe, tone), removable=False)
        for exe, tone in saved.items():
            if exe not in DEFAULT_TONOS:
                self._add_tone_row(exe, tone, removable=True)
        add = QHBoxLayout()
        self.exe_edit = QLineEdit()
        self.exe_edit.setPlaceholderText("Otro programa (ej. notion.exe)")
        self.exe_edit.returnPressed.connect(self._add_custom_tone)
        self.exe_tone = QComboBox()
        polish_combo(self.exe_tone)
        fill_combo(self.exe_tone, TONE_EDIT, "formal")
        add_btn = button("Agregar", "ghost")
        add_btn.clicked.connect(self._add_custom_tone)
        add.addWidget(self.exe_edit, 1)
        add.addWidget(self.exe_tone)
        add.addWidget(add_btn)
        al.addLayout(add)
        lay.addWidget(apps)

        lay.addWidget(section_label("SISTEMA Y PRIVACIDAD"))
        self.sw_son = Switch(cfg.get("sonidos", True))
        self.sw_son.toggled.connect(lambda *_: self._auto_save())
        self.sw_ini = Switch(cfg.get("inicio_windows", False))
        self.sw_ini.toggled.connect(lambda *_: self._auto_save())
        self.sw_priv = Switch(bool(cfg.get("privacidad")))
        self.sw_priv.toggled.connect(lambda *_: self._auto_save())
        lay.addWidget(switch_row("Sonidos de inicio y fin", "Reproduce un tono sutil al empezar a escuchar y al pegar.", self.sw_son))
        lay.addWidget(switch_row("Iniciar junto con Windows", "Deja Dictado Libre listo junto al reloj al prender la PC.", self.sw_ini))
        lay.addWidget(switch_row("Modo Privacidad estricta", "Fuerza que ni el audio ni el texto salgan jamás de esta computadora.", self.sw_priv))
        lay.addStretch(1)
        return page

    def _hotkey_card(self, title, subtitle, target, attr):
        box = card()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 13, 14, 13)
        bl.setSpacing(8)
        bl.addWidget(card_title(title))
        lab = QLabel(pretty_hotkey(getattr(self, attr)))
        lab.setObjectName("hotkey")
        lab.setAlignment(Qt.AlignCenter)
        btn = button("Cambiar atajo", "ghost")
        btn.clicked.connect(lambda _=False, t=target: self._begin_capture(t))
        bl.addWidget(lab)
        bl.addWidget(btn)
        bl.addWidget(muted(subtitle))
        if target == "cmd":
            self.hk_cmd_label, self.hk_cmd_btn = lab, btn
        elif target == "escribir":
            self.hk_write_label, self.hk_write_btn = lab, btn
        else:
            self.hk_label, self.hk_btn = lab, btn
        return box

    def _add_tone_row(self, exe, tone, removable):
        exe = (exe or "").strip().lower()
        if not exe:
            return
        for item in self._tone_widgets:
            if item["exe"] == exe:
                i = item["combo"].findData(tone)
                if i >= 0:
                    item["combo"].setCurrentIndex(i)
                return
        row = card("subcard")
        row.setMinimumHeight(46)
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 6, 12, 6)
        lab = QLabel(APP_NAMES.get(exe, exe))
        lab.setWordWrap(True)
        combo = QComboBox()
        polish_combo(combo)
        fill_combo(combo, TONE_EDIT, tone if tone in dict(TONE_EDIT) else "mantener")
        combo.setMinimumWidth(145)
        combo.currentIndexChanged.connect(lambda *_: self._auto_save())
        h.addWidget(lab, 1)
        h.addWidget(combo)
        if removable:
            rm = button("Quitar", "danger")
            rm.clicked.connect(lambda _=False, e=exe: (self._remove_tone(e), self._auto_save()))
            h.addWidget(rm)
        self.tone_box.addWidget(row)
        self._tone_widgets.append({"exe": exe, "combo": combo, "row": row})

    def _remove_tone(self, exe):
        keep = []
        for item in self._tone_widgets:
            if item["exe"] == exe:
                self.tone_box.removeWidget(item["row"])
                item["row"].deleteLater()
            else:
                keep.append(item)
        self._tone_widgets = keep

    def _add_custom_tone(self):
        name = self.exe_edit.text().strip().lower()
        if not name:
            return
        if not name.endswith(".exe"):
            name += ".exe"
        self._add_tone_row(name, self.exe_tone.currentData() or "formal", removable=True)
        self.exe_edit.clear()
        self._auto_save()

    # ---------- 3. VOCABULARIO ----------
    def _page_words(self):
        page, lay = self._page_shell(
            "Vocabulario",
            "Agregá nombres propios, siglas técnicas y fragmentos de voz apretando Enter. Se guardan al instante.")
        self.sw_learn = Switch(bool(cfg.get("aprender", True)))
        self.sw_learn.toggled.connect(lambda *_: self._auto_save())
        lay.addWidget(switch_row(
            "Aprender correcciones automáticamente",
            "Si corregís una palabra apenas la pega, te ofrece guardarla en tu diccionario con un clic.",
            self.sw_learn))

        # --- Diccionario personal ---
        lay.addWidget(section_label("DICCIONARIO PERSONAL"))
        box = card()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(10)
        d_hdr = QHBoxLayout()
        d_hdr.addWidget(card_title("Palabras, nombres y términos técnicos"), 1)
        self.dict_count_lbl = muted("0 palabras")
        d_hdr.addWidget(self.dict_count_lbl)
        bl.addLayout(d_hdr)
        bl.addWidget(muted("Escribí cómo querés que se escriba (y opcionalmente cómo suena) y apretá Enter para sumarla."))

        q_dict = QHBoxLayout()
        q_dict.setSpacing(8)
        self.dict_new_escribe = QLineEdit()
        self.dict_new_escribe.setPlaceholderText("Nueva palabra (ej. Kubernetes, Facundo, Groq)…")
        self.dict_new_escribe.returnPressed.connect(self._quick_add_dict)
        self.dict_new_oye = QLineEdit()
        self.dict_new_oye.setPlaceholderText("Si suena distinto (opcional)…")
        self.dict_new_oye.returnPressed.connect(self._quick_add_dict)
        self.dict_new_tipo = QComboBox()
        polish_combo(self.dict_new_tipo)
        fill_combo(self.dict_new_tipo, DICT_TYPES, "nombre")
        self.dict_new_tipo.setMinimumWidth(110)
        add_d = button("+ Agregar", "primary")
        add_d.clicked.connect(self._quick_add_dict)
        q_dict.addWidget(self.dict_new_escribe, 3)
        q_dict.addWidget(self.dict_new_oye, 2)
        q_dict.addWidget(self.dict_new_tipo, 1)
        q_dict.addWidget(add_d)
        bl.addLayout(q_dict)

        self.dict_empty = muted("Todavía no agregaste palabras. Escribí arriba y apretá Enter para guardar la primera.")
        bl.addWidget(self.dict_empty)
        self.dict_box = QVBoxLayout()
        self.dict_box.setSpacing(6)
        bl.addLayout(self.dict_box)
        self._dict_rows = []
        for entry in cfg.get("diccionario") or []:
            self._add_dict_row(entry)
        self._sync_vocab_counts()
        lay.addWidget(box)

        # --- Fragmentos de voz ---
        lay.addWidget(section_label("FRAGMENTOS DE VOZ (ATAJOS DE TEXTO)"))
        snippets = card()
        sl = QVBoxLayout(snippets)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.setSpacing(10)
        s_hdr = QHBoxLayout()
        s_hdr.addWidget(card_title("Reemplazos rápidos por voz"), 1)
        self.snip_count_lbl = muted("0 fragmentos")
        s_hdr.addWidget(self.snip_count_lbl)
        sl.addLayout(s_hdr)
        sl.addWidget(muted("Decís una frase corta (ej. «mi correo» o «mi firma») y pega el texto largo automáticamente."))

        q_snip = QHBoxLayout()
        q_snip.setSpacing(8)
        self.snip_new_frase = QLineEdit()
        self.snip_new_frase.setPlaceholderText("Cuando diga… (ej. mi correo)")
        self.snip_new_frase.returnPressed.connect(self._quick_add_snip)
        self.snip_new_texto = QLineEdit()
        self.snip_new_texto.setPlaceholderText("Pegar este texto… (ej. facundo@ejemplo.com)")
        self.snip_new_texto.returnPressed.connect(self._quick_add_snip)
        add_s = button("+ Agregar", "primary")
        add_s.clicked.connect(self._quick_add_snip)
        q_snip.addWidget(self.snip_new_frase, 2)
        q_snip.addWidget(self.snip_new_texto, 4)
        q_snip.addWidget(add_s)
        sl.addLayout(q_snip)

        self.snip_empty = muted("Todavía no tenés fragmentos. Cargá una frase corta arriba y apretá Enter.")
        sl.addWidget(self.snip_empty)
        self.snip_box = QVBoxLayout()
        self.snip_box.setSpacing(6)
        sl.addLayout(self.snip_box)
        self._snip_rows = []
        for item in cfg.get("fragmentos") or []:
            self._add_snip_row(item)
        self._sync_vocab_counts()
        lay.addWidget(snippets)
        lay.addStretch(1)
        return page

    def _sync_vocab_counts(self):
        if hasattr(self, "dict_count_lbl") and hasattr(self, "_dict_rows"):
            n = len(self._dict_rows)
            self.dict_count_lbl.setText(f"{n} {'palabra' if n == 1 else 'palabras'}")
            if hasattr(self, "dict_empty"):
                self.dict_empty.setVisible(n == 0)
        if hasattr(self, "snip_count_lbl") and hasattr(self, "_snip_rows"):
            m = len(self._snip_rows)
            self.snip_count_lbl.setText(f"{m} {'fragmento' if m == 1 else 'fragmentos'}")
            if hasattr(self, "snip_empty"):
                self.snip_empty.setVisible(m == 0)

    def _quick_add_dict(self):
        escribe = self.dict_new_escribe.text().strip()
        oye = self.dict_new_oye.text().strip()
        tipo = self.dict_new_tipo.currentData() or ("nombre" if escribe[:1].isupper() else "jerga")
        if not escribe:
            self.dict_new_escribe.setFocus()
            return
        for row in list(self._dict_rows):
            try:
                if row["escribe"].text().strip().lower() == escribe.lower():
                    if oye:
                        row["oye"].setText(oye)
                    i = row["tipo"].findData(tipo)
                    if i >= 0:
                        row["tipo"].setCurrentIndex(i)
                    self.dict_new_escribe.clear()
                    self.dict_new_oye.clear()
                    self.dict_new_escribe.setFocus()
                    self._auto_save()
                    return
            except RuntimeError:
                pass
        self._add_dict_row({"escribe": escribe, "oye": oye, "tipo": tipo})
        self.dict_new_escribe.clear()
        self.dict_new_oye.clear()
        self.dict_new_escribe.setFocus()
        self._sync_vocab_counts()
        self._auto_save()

    def _quick_add_snip(self):
        frase = self.snip_new_frase.text().strip()
        texto = self.snip_new_texto.text().strip()
        if not frase or not texto:
            (self.snip_new_frase if not frase else self.snip_new_texto).setFocus()
            return
        self._add_snip_row({"frase": frase, "texto": texto})
        self.snip_new_frase.clear()
        self.snip_new_texto.clear()
        self.snip_new_frase.setFocus()
        self._sync_vocab_counts()
        self._auto_save()

    def _add_dict_row(self, entry):
        row = card("subcard")
        row.setMinimumHeight(46)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        escribe = QLineEdit(entry.get("escribe") or "")
        escribe.setPlaceholderText("Cómo se escribe")
        escribe.textChanged.connect(lambda *_: self._schedule_save())
        arrow = muted("← suena:")
        oye = QLineEdit(entry.get("oye") or "")
        oye.setPlaceholderText("igual / variante fonética")
        oye.textChanged.connect(lambda *_: self._schedule_save())
        tipo = QComboBox()
        polish_combo(tipo)
        fill_combo(tipo, DICT_TYPES, entry.get("tipo") or "jerga")
        tipo.setMinimumWidth(104)
        tipo.currentIndexChanged.connect(lambda *_: self._auto_save())
        rm = button("Quitar", "danger")
        lay.addWidget(escribe, 3)
        lay.addWidget(arrow)
        lay.addWidget(oye, 2)
        lay.addWidget(tipo, 1)
        lay.addWidget(rm)
        item = {"escribe": escribe, "oye": oye, "tipo": tipo, "row": row}
        rm.clicked.connect(lambda _=False, it=item: (self._remove_dict_row(it), self._sync_vocab_counts(), self._auto_save()))
        self.dict_box.addWidget(row)
        self._dict_rows.append(item)
        self._sync_vocab_counts()

    def _remove_dict_row(self, item):
        self.dict_box.removeWidget(item["row"])
        item["row"].deleteLater()
        self._dict_rows = [row for row in self._dict_rows if row is not item]

    def _add_snip_row(self, entry):
        row = card("subcard")
        row.setMinimumHeight(46)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        frase = QLineEdit(entry.get("frase") or "")
        frase.setPlaceholderText("Frase que decís")
        frase.textChanged.connect(lambda *_: self._schedule_save())
        arrow = muted("→")
        raw_txt = entry.get("texto") or ""
        texto = QLineEdit(raw_txt.replace("\n", " ↵ "))
        texto.setPlaceholderText("Texto completo que se pega")
        texto.textChanged.connect(lambda *_: self._schedule_save())
        rm = button("Quitar", "danger")
        lay.addWidget(frase, 2)
        lay.addWidget(arrow)
        lay.addWidget(texto, 4)
        lay.addWidget(rm)
        item = {"frase": frase, "texto": texto, "row": row}
        rm.clicked.connect(lambda _=False, it=item: (self._remove_snip_row(it), self._sync_vocab_counts(), self._auto_save()))
        self.snip_box.addWidget(row)
        self._snip_rows.append(item)
        self._sync_vocab_counts()

    def _remove_snip_row(self, item):
        self.snip_box.removeWidget(item["row"])
        item["row"].deleteLater()
        self._snip_rows = [row for row in self._snip_rows if row is not item]

    def _collect_dict(self):
        items = []
        for row in list(self._dict_rows):
            try:
                items.append({
                    "escribe": row["escribe"].text().strip(),
                    "oye": row["oye"].text().strip(),
                    "tipo": row["tipo"].currentData() or "jerga",
                })
            except RuntimeError:
                pass
        return _clean_dict_entries(items)

    def _collect_snips(self):
        items = []
        for row in list(self._snip_rows):
            try:
                txt_widget = row["texto"]
                raw = txt_widget.text() if hasattr(txt_widget, "text") else txt_widget.toPlainText()
                items.append({"frase": row["frase"].text().strip(), "texto": raw.replace(" ↵ ", "\n").strip()})
            except RuntimeError:
                pass
        return _clean_snippets(items)

    def note_learned(self, oye, escribe):
        for row in list(self._dict_rows):
            try:
                if row["escribe"].text().strip().lower() == escribe.lower():
                    row["oye"].setText(oye)
                    row["escribe"].setText(escribe)
                    return
            except RuntimeError:
                continue
        self._add_dict_row({"escribe": escribe, "oye": oye, "tipo": "nombre" if (escribe[:1].isupper()) else "jerga"})

    def _metric(self, value, caption):
        box = card()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(2)
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
        if hasattr(self, "groq_hint"):
            if value == "online" and not self.key.text().strip():
                self.groq_hint.setText("Pegá tu clave gratis de Groq arriba para activar el modo online (mientras tanto usa el modo local).")
            else:
                self.groq_hint.setText("La clave también mejora el pulido de texto, Comando y Ayudame a escribir.")

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
        if controller is not None and self.isVisible() and self.stack.currentIndex() == 1:
            controller.start_monitor(self.mic.currentData() or "")

    def _select_nav(self, index):
        for i, (kind, b) in enumerate(self.nav):
            active = (i == index)
            b.setChecked(active)
            b.setIcon(nav_icon(kind, active=active))

    def open_page(self, index):
        if index in (5, 6):
            index = 0
        elif index >= 4:
            index = 3
        self.stack.setCurrentIndex(index)
        self._select_nav(index)
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_page(self, index):
        self._select_nav(index)
        if index == 0:
            self._refresh_stats()
            self._refresh_history()
        if controller is not None:
            if index == 1 and self.isVisible():
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
            self.update_hint.setText("Hay una versión nueva disponible.")
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

    def _begin_capture(self, target="atajo"):
        global capturing
        capturing = True
        self._capturing = True
        self._cap_target = target
        _unhook_hotkeys()
        btn, lab = self._hotkey_widgets(target)
        btn.setText("Escuchando teclas… (Esc cancela)")
        lab.setText("Apretá las teclas…")
        self.setFocus()
        self.grabKeyboard()

    def _hotkey_widgets(self, target):
        if target == "cmd":
            return self.hk_cmd_btn, self.hk_cmd_label
        if target == "escribir":
            return self.hk_write_btn, self.hk_write_label
        return self.hk_btn, self.hk_label

    def _sync_hotkey_labels(self):
        self.hotkey = cfg.get("atajo") or self.hotkey or "ctrl+alt+space"
        self.hotkey_cmd = cfg.get("atajo_cmd") or self.hotkey_cmd or "ctrl+alt+shift+space"
        self.hotkey_write = cfg.get("atajo_escribir") or self.hotkey_write or "ctrl+alt+a"
        self.hk_label.setText(pretty_hotkey(self.hotkey))
        self.hk_cmd_label.setText(pretty_hotkey(self.hotkey_cmd))
        self.hk_write_label.setText(pretty_hotkey(self.hotkey_write))
        self._sync_playground_placeholder()

    def _end_capture(self, apply_live=True):
        global capturing
        if not self._capturing:
            return
        capturing = False
        self._capturing = False
        self.releaseKeyboard()
        btn, _lab = self._hotkey_widgets(self._cap_target)
        btn.setText("Cambiar atajo")
        if apply_live:
            register_hotkey(announce=False)
        self._sync_hotkey_labels()

    def keyPressEvent(self, e):
        if not self._capturing:
            super().keyPressEvent(e)
            return
        if e.isAutoRepeat():
            return
        if e.key() == Qt.Key_Escape:
            self._end_capture(apply_live=True)
            return
        name = _qt_key_name(e.key(), e.text())
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
        combo = "+".join(mods + [name]).strip().lower()
        target_map = {"cmd": "atajo_cmd", "escribir": "atajo_escribir", "atajo": "atajo"}
        cfg_key = target_map.get(self._cap_target, "atajo")
        other_combos = {
            (cfg.get(k) or "").strip().lower()
            for k in ("atajo", "atajo_cmd", "atajo_escribir")
            if k != cfg_key
        }
        if combo in other_combos:
            self._end_capture(apply_live=True)
            self._alert("Atajos", "Esa combinación ya está en uso por otro atajo. Elegí una distinta.")
            return
        prev_val = cfg.get(cfg_key)
        cfg[cfg_key] = combo
        if self._cap_target == "cmd":
            self.hotkey_cmd = combo
        elif self._cap_target == "escribir":
            self.hotkey_write = combo
        else:
            self.hotkey = combo
        save()
        self._end_capture(apply_live=True)
        if cfg.get(cfg_key) != combo:
            cfg[cfg_key] = prev_val
            save()
            register_hotkey(announce=False)
            self._sync_hotkey_labels()
            self._alert("Atajo", "Esa combinación no pudo registrarse en Windows. Probá otra.")
        else:
            self._flash_saved(f"✓ Atajo activo: {pretty_hotkey(combo)}")

    def _auto_save(self):
        if getattr(self, "_initializing", False):
            return
        key = self.key.text().strip()
        modo = self.modo
        self._set_modo(modo)
        old_model = cfg.get("modelo")
        old_ini = cfg.get("inicio_windows")
        tono = self.tone_combo.currentData() or "auto"
        tonos = {}
        for item in self._tone_widgets:
            try:
                tonos[item["exe"]] = item["combo"].currentData() or "mantener"
            except RuntimeError:
                pass
        cfg.update(
            modo=modo, groq_key=key, pulir=self.sw_pulir.isChecked(),
            modo_tecla=self.tecla, modelo=self.model.currentData() or "small",
            tono=tono, estilo=tono if tono != "auto" else cfg.get("estilo", "mantener"),
            idioma=self.lang.currentData() or "es",
            sonidos=self.sw_son.isChecked(), inicio_windows=self.sw_ini.isChecked(),
            microfono=self.mic.currentData() or "", traducir_en=self.sw_en.isChecked(), tonos=tonos,
            susurro=self.sw_sus.isChecked(), privacidad=self.sw_priv.isChecked(), aprender=self.sw_learn.isChecked(),
            diccionario=self._collect_dict(), fragmentos=self._collect_snips())
        save()
        if old_ini != cfg["inicio_windows"]:
            set_autostart(cfg["inicio_windows"])
        if old_model != cfg["modelo"]:
            global _model
            _model = None
            if cfg["modo"] == "local" or not cfg["groq_key"] or cfg.get("privacidad"):
                threading.Thread(target=_preload, daemon=True).start()
        self._flash_saved("✓ Guardado en vivo")

    def _save(self):
        self._auto_save()

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
        query = (self.hist_search.text().strip().lower() if hasattr(self, "hist_search") else "")
        if not hist:
            self.hist_box.addWidget(muted("Todavía no dictaste nada. Probá en la Caja de prueba rápida de arriba."))
            return
        shown = 0
        for i, item in enumerate(hist[:100]):
            if query and query not in (item.get("text") or "").lower():
                continue
            self.hist_box.addWidget(self._hist_card(i, item))
            shown += 1
        if shown == 0:
            self.hist_box.addWidget(muted("No hay dictados que coincidan con tu búsqueda."))

    def _hist_card(self, index, item):
        box = card()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
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
        audio_path = item.get("audio")
        ts_val = item.get("ts")
        copy_b.clicked.connect(lambda _=False, t=raw, b=copy_b: self._copy_text(t, b))
        paste_b.clicked.connect(lambda _=False, t=raw, b=paste_b: self._repaste(t, b))
        del_b.clicked.connect(lambda _=False, n=index: delete_history(n))
        actions.addWidget(copy_b)
        actions.addWidget(paste_b)
        if audio_path and os.path.exists(audio_path):
            retry_b = button("Reintentar transcripción", "chip")
            retry_b.clicked.connect(lambda _=False, ap=audio_path, ts=ts_val, b=retry_b: self._retry_hist(ap, ts, b))
            actions.addWidget(retry_b)
        actions.addWidget(del_b)
        actions.addStretch(1)
        lay.addLayout(actions)
        return box

    def _retry_hist(self, audio_path, ts, btn):
        btn.setText("Reintentando…")
        btn.setEnabled(False)
        retry_transcription(audio_path=audio_path, hist_ts=ts, paste_result=False)

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
                paste(text, watch=False)
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
            self.last_label.setText("Todavía no hay dictados. El tiempo ahorrado compara tu voz con tipear a 40 palabras por minuto.")
            return
        lw, ls, lp = int(m.get("last_words", 0) or 0), float(m.get("last_seconds", 0) or 0), int(m.get("last_wpm", 0) or 0)
        self.last_label.setText(
            f"Último dictado: {fmt_int(lw)} palabras en {fmt_span(ls)} ({fmt_int(lp)} palabras/min)  ·  "
            f"Total: {fmt_int(m.get('sessions', 0))} dictados.")

    def showEvent(self, e):
        super().showEvent(e)
        self._dark_title()
        self._center()
        self._refresh_update()
        if controller is not None and self.stack.currentIndex() == 1:
            controller.start_monitor(self.mic.currentData() or "")

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

def _qt_key_name(key, text=""):
    if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R):
        return None
    special = {
        Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Tab: "tab",
        Qt.Key_Backspace: "backspace", Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left",
        Qt.Key_Right: "right", Qt.Key_Delete: "delete", Qt.Key_Insert: "insert", Qt.Key_Home: "home",
        Qt.Key_End: "end", Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down",
        Qt.Key_Plus: "+", Qt.Key_Minus: "-", Qt.Key_Comma: ",", Qt.Key_Period: ".",
        Qt.Key_Slash: "/", Qt.Key_Backslash: "\\", Qt.Key_Semicolon: ";", Qt.Key_Apostrophe: "'",
        Qt.Key_BracketLeft: "[", Qt.Key_BracketRight: "]", Qt.Key_QuoteLeft: "`",
    }
    if key in special:
        return special[key]
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"f{key - Qt.Key_F1 + 1}"
    if Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key).lower()
    if text and len(text) == 1 and text.isprintable() and not text.isspace():
        return text.lower()
    return None

class LearnPopup(QWidget):
    def __init__(self):
        super().__init__()
        self.old, self.new = "", ""
        self.setObjectName("learn")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QWidget#learn { background:#1b1e27; border:1px solid #343848; border-radius:16px; }"
            "QLabel { color:#f4f5f7; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(380)
        lay.addWidget(self.label)
        row = QHBoxLayout()
        yes = button("Guardar", "primary")
        no = button("Ahora no", "ghost")
        yes.clicked.connect(self._save)
        no.clicked.connect(self.hide)
        row.addWidget(yes)
        row.addWidget(no)
        row.addStretch(1)
        lay.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def offer(self, old, new):
        self.old, self.new = old, new
        self.label.setText(f"Cambiaste «{old}» por «{new}». ¿Lo guardo en el diccionario?")
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start(14000)

    def _place(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.x() + (geo.width() - self.width()) // 2, geo.y() + geo.height() - self.height() - 130)

    def _save(self):
        old, new = self.old, self.new
        self.hide()
        if old and new:
            add_dictionary_correction(old, new)
            notify(f"Listo. La próxima vez escribo «{new}».")

class App(QObject):
    def __init__(self, qapp):
        super().__init__()
        global controller
        controller = self
        self.app = qapp
        self.mon = None
        self.settings = None
        self.pill = Pill()
        self.learn = LearnPopup()
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
        self.act_cfg = QAction("Inicio y métricas", self.menu)
        self.act_cfg.triggered.connect(lambda: self.open_settings(0))
        self.act_voice = QAction("Voz y micrófono", self.menu)
        self.act_voice.triggered.connect(lambda: self.open_settings(1))
        self.act_write = QAction("Escritura y atajos", self.menu)
        self.act_write.triggered.connect(lambda: self.open_settings(2))
        self.act_words = QAction("Vocabulario", self.menu)
        self.act_words.triggered.connect(lambda: self.open_settings(3))
        self.act_log = QAction("Abrir registro de errores", self.menu)
        self.act_log.triggered.connect(self._open_log)
        self.act_quit = QAction("Salir", self.menu)
        self.act_quit.triggered.connect(self.quit)
        for act in (self.act_ver, self.act_update, self.act_check):
            self.menu.addAction(act)
        self.menu.addSeparator()
        self.menu.addAction(self.act_cfg)
        self.menu.addAction(self.act_voice)
        self.menu.addAction(self.act_write)
        self.menu.addAction(self.act_words)
        self.menu.addSeparator()
        self.menu.addAction(self.act_log)
        self.menu.addAction(self.act_quit)
        self.menu.aboutToShow.connect(self._sync_update_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.show()
        bridge.state_changed.connect(self._on_state)
        bridge.notice.connect(self._notice)
        bridge.learn_offer.connect(self.learn.offer)
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
            "comando": "Comando", "escribir": "Ayuda", "formal": "Tono formal",
            "mensaje": "Tono chat", "tecnico": "Tono técnico",
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
        if self.pill.state == "listo":
            self.pill.on_state("listo", "listo")

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
                if bridge is not None:
                    bridge.mic_level.emit(chunk_level(indata))

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
        if self.settings is None or not self.settings.isVisible() or self.settings.stack.currentIndex() != 1:
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

def _whats_new(mention_pill=False, mention_write=False):
    extra = ""
    if mention_pill:
        extra += "Al dictar, aparece una pastilla abajo en el centro con la onda de tu voz.\n\n"
    if mention_write:
        cmd = pretty_hotkey(cfg.get("atajo_cmd") or "ctrl+alt+shift+space")
        write = pretty_hotkey(cfg.get("atajo_escribir") or "ctrl+alt+a")
        extra += (
            "El tono sigue al programa. "
            f"Comando ({cmd}) transforma un texto seleccionado, y Ayudame a escribir ({write}) arma un mensaje.\n\n")
    if _dialog(
        APP,
        extra + "Ahora podés enseñarle palabras.\n\n"
        "En Palabras anotás nombres, siglas y jerga. El dictado trata de escribirlas así.\n\n"
        "Si corregís una palabra justo después de pegar, y se puede ver el cambio, te ofrece guardarla.\n\n"
        "Un fragmento cambia una frase corta por un texto largo.\n\n"
        "Modo susurro, en Micrófono, sube la voz baja. "
        "Privacidad, en General, deja el audio y el texto en esta computadora.",
        "Abrir Palabras"):
        if controller is not None:
            controller.open_settings(4)

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
    if cfg.get("privacidad") or cfg.get("modo") == "local" or not cfg.get("groq_key"):
        threading.Thread(target=_preload, daemon=True).start()
    else:
        set_state("listo", "")
    if cfg.get("primera_vez"):
        cfg["primera_vez"] = False
        save()
        QTimer.singleShot(400, lambda: (_welcome(), controller.open_settings(0)))
    else:
        if "--tray" not in sys.argv:
            QTimer.singleShot(200, lambda: controller.open_settings(0))
        mention_pill = bool(cfg.pop("_from_old", False))
        mention_write = bool(cfg.pop("_from_12", False))
        mention_words = bool(cfg.pop("_from_13", False))
        if mention_pill or mention_write or mention_words:
            save()
            QTimer.singleShot(500, lambda p=mention_pill, w=mention_write: _whats_new(p, w))
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
