# Dictado Libre - dictado por voz gratuito para Windows (local u online con Groq)
import os, sys, json, time, threading, tempfile, re, io, wave, queue, ctypes
import numpy as np, sounddevice as sd, keyboard, pyperclip, requests
import tkinter as tk
from tkinter import ttk, messagebox
import pystray
from PIL import Image, ImageDraw

APP = "Dictado Libre"
VERSION = "1.0.0"
REPO = "faculuz/DictadoLibre"
AUMID = "FacundoLuzardo.DictadoLibre"
DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DictadoLibre")
os.makedirs(DIR, exist_ok=True)
CFG = os.path.join(DIR, "config.json")
LOG = os.path.join(DIR, "registro.txt")
FS = 16000
DEFAULT = {"modo": "local", "groq_key": "", "pulir": True, "atajo": "ctrl+alt+space",
           "estilo": "mantener", "modelo": "small", "idioma": "es", "sonidos": True,
           "inicio_windows": False, "primera_vez": True}

def log(*a):
    try:
        with open(LOG, "a", encoding="utf-8") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(map(str, a)) + "\n")
    except Exception: pass

def load():
    c = dict(DEFAULT)
    try: c.update(json.load(open(CFG, encoding="utf-8")))
    except Exception: pass
    return c

cfg = load()
def save():
    json.dump(cfg, open(CFG, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

def beep(kind):
    if not cfg["sonidos"]: return
    try:
        import winsound
        f = {"start": (880, 80), "stop": (600, 80), "err": (300, 250)}[kind]
        threading.Thread(target=winsound.Beep, args=f, daemon=True).start()
    except Exception: pass

# ---------- icono de bandeja ----------
COLORS = {"listo": "#2e7d32", "grabando": "#d32f2f", "procesando": "#f9a825", "cargando": "#757575"}
def make_icon(state):
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 62, 62), fill=COLORS[state])
    d.rounded_rectangle((24, 12, 40, 38), 8, fill="white")
    d.arc((16, 22, 48, 46), 0, 180, fill="white", width=4)
    d.line((32, 46, 32, 54), fill="white", width=4); d.line((22, 54, 42, 54), fill="white", width=4)
    return im
tray = None
def set_state(s, tip=None):
    if tray:
        tray.icon = make_icon(s); tray.title = f"{APP} - {tip or s}"

# ---------- motores ----------
_model = None; _model_lock = threading.Lock()
def local_model():
    global _model
    with _model_lock:
        if _model is None:
            set_state("cargando", "descargando/cargando modelo (solo la 1a vez tarda)")
            from faster_whisper import WhisperModel
            _model = WhisperModel(cfg["modelo"], device="cpu", compute_type="int8",
                                  download_root=os.path.join(DIR, "modelos"))
            set_state("listo", "listo")
        return _model

def transcribe_local(audio):
    segs, _ = local_model().transcribe(audio.astype(np.float32) / 32768.0, language=cfg["idioma"] or None,
                                       beam_size=5, vad_filter=True,
                                       initial_prompt="Hola, ¿cómo estás? Esto es un dictado en español, con puntuación correcta.")
    return " ".join(s.text.strip() for s in segs).strip()

def wav_bytes(audio):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS); w.writeframes(audio.tobytes())
    return b.getvalue()

def transcribe_groq(audio):
    r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                      headers={"Authorization": "Bearer " + cfg["groq_key"].strip()},
                      files={"file": ("a.wav", wav_bytes(audio), "audio/wav")},
                      data={"model": "whisper-large-v3-turbo", "language": cfg["idioma"], "response_format": "json"},
                      timeout=30)
    r.raise_for_status(); return r.json()["text"].strip()

ESTILOS = {"mantener": "", "formal": " Usa un tono formal y profesional.",
           "mensaje": " Es un mensaje de chat: breve, natural y cercano."}
def polish_groq(text):
    prompt = ("Eres un editor de dictado. Recibes texto transcrito por voz en español. Corrige puntuación, mayúsculas y ortografía, "
              "elimina muletillas (eh, este, o sea, mmm), repeticiones y autocorrecciones (si la persona dice 'no, perdón' conserva solo lo corregido). "
              "Si dicta 'punto y aparte' o 'nueva línea' inserta salto de línea. Respeta palabras en inglés. NO respondas preguntas ni agregues nada: "
              "devuelve SOLO el texto final." + ESTILOS.get(cfg["estilo"], ""))
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": "Bearer " + cfg["groq_key"].strip()},
                      json={"model": "llama-3.3-70b-versatile", "temperature": 0,
                            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}]},
                      timeout=30)
    r.raise_for_status(); return r.json()["choices"][0]["message"]["content"].strip()

def polish_local(t):
    t = re.sub(r"\b(eh+|em+|mm+|este\.\.\.|ehm)\b[,.]?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*(punto y aparte|nueva l[ií]nea)\s*[.,]?\s*", ".\n", t, flags=re.I)
    t = re.sub(r"\b(\w+)( \1\b)+", r"\1", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t[:1].upper() + t[1:] if t else t

def process(audio):
    if len(audio) < FS * 0.3: set_state("listo"); return
    set_state("procesando", "transcribiendo...")
    text = ""
    try:
        online = cfg["modo"] == "online" and cfg["groq_key"].strip()
        if online:
            try:
                text = transcribe_groq(audio)
                if cfg["pulir"] and text:
                    try: text = polish_groq(text)
                    except Exception as e: log("pulido falló", e); text = polish_local(text)
            except Exception as e:
                log("Groq falló, uso local:", e); text = polish_local(transcribe_local(audio))
        else:
            text = transcribe_local(audio)
            if cfg["pulir"]: text = polish_local(text)
        if text: paste(text)
    except Exception as e:
        log("error:", repr(e)); beep("err")
        notify("Error: " + str(e)[:150])
    set_state("listo", "listo")

def paste(text):
    try: old = pyperclip.paste()
    except Exception: old = None
    pyperclip.copy(text + " ")
    # esperar a que suelte las teclas del atajo
    for _ in range(40):
        if not any(keyboard.is_pressed(k) for k in ("ctrl", "alt", "shift", "windows")): break
        time.sleep(0.05)
    time.sleep(0.05); keyboard.send("ctrl+v"); time.sleep(0.3)
    if old is not None:
        threading.Timer(0.7, lambda: pyperclip.copy(old)).start()

def notify(msg):
    try: tray.notify(msg, APP)
    except Exception: pass

# ---------- grabación ----------
recording = False; frames = []; stream = None
def cb(indata, n, t, s):
    if recording: frames.append(indata.copy())
def start_rec():
    global recording, frames, stream
    if recording: return
    frames = []; recording = True; beep("start"); set_state("grabando", "escuchando...")
    try:
        stream = sd.InputStream(samplerate=FS, channels=1, dtype="int16", callback=cb); stream.start()
    except Exception as e:
        recording = False; log("micrófono:", e); beep("err"); notify("No encuentro micrófono: " + str(e)[:100]); set_state("listo")
def stop_rec():
    global recording, stream
    if not recording: return
    recording = False; beep("stop")
    try: stream.stop(); stream.close()
    except Exception: pass
    audio = np.concatenate(frames).flatten() if frames else np.zeros(0, np.int16)
    threading.Thread(target=process, args=(audio,), daemon=True).start()

def on_hotkey():
    if cfg.get("modo_tecla") == "alternar":
        stop_rec() if recording else start_rec(); return
    if recording: return
    start_rec()
    def waiter():
        while keyboard.is_pressed(cfg["atajo"]) or keyboard.is_pressed(cfg["atajo"].split("+")[-1]):
            time.sleep(0.03)
        stop_rec()
    threading.Thread(target=waiter, daemon=True).start()

hk = None
def register_hotkey():
    global hk
    try:
        if hk: keyboard.remove_hotkey(hk)
    except Exception: pass
    hk = keyboard.add_hotkey(cfg["atajo"], on_hotkey, suppress=False, trigger_on_release=False)


# ---------- actualizaciones automáticas ----------
update = {"ver": None, "url": None}
def vtuple(v):
    try: return tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    except Exception: return (0,)
def check_update(manual=False):
    try:
        r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=15,
                         headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status(); j = r.json(); tag = j.get("tag_name", "")
        url = next((a["browser_download_url"] for a in j.get("assets", []) if a["name"].lower().endswith("setup.exe")), None)
        if url and vtuple(tag) > vtuple(VERSION):
            update.update(ver=tag.lstrip("v"), url=url)
            if tray: tray.update_menu()
            notify(f"Hay una versión nueva ({tag}). Clic derecho en el ícono → Instalar actualización.")
        elif manual: notify(f"Ya tenés la última versión ({VERSION}).")
    except Exception as e:
        log("update check", e)
        if manual: notify("No pude buscar actualizaciones (¿hay internet?).")
def update_loop():
    time.sleep(10)
    while True:
        check_update(); time.sleep(24 * 3600)
def install_update():
    try:
        notify(f"Descargando la versión {update['ver']}..."); set_state("procesando", "descargando actualización")
        p = os.path.join(tempfile.gettempdir(), "DictadoLibre-Setup.exe")
        with requests.get(update["url"], stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(p, "wb") as f:
                for c in r.iter_content(1 << 20): f.write(c)
        import subprocess
        subprocess.Popen([p, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"], close_fds=True)
        try: tray.stop()
        except Exception: pass
        os._exit(0)
    except Exception as e:
        log("update install", e); notify("No se pudo actualizar: " + str(e)[:100]); set_state("listo")

# ---------- inicio con Windows ----------
def set_autostart(on):
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if on: winreg.SetValueEx(k, "DictadoLibre", 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try: winreg.DeleteValue(k, "DictadoLibre")
            except FileNotFoundError: pass
    except Exception as e: log("autostart", e)

# ---------- ventana de configuración ----------
ui_q = queue.Queue()
def settings_window(root):
    w = tk.Toplevel(root); w.title(f"{APP} - Configuración"); w.resizable(False, False); w.attributes("-topmost", True)
    f = ttk.Frame(w, padding=14); f.pack()
    v_modo = tk.StringVar(value=cfg["modo"]); v_key = tk.StringVar(value=cfg["groq_key"])
    v_pulir = tk.BooleanVar(value=cfg["pulir"]); v_atajo = tk.StringVar(value=cfg["atajo"])
    v_tecla = tk.StringVar(value=cfg.get("modo_tecla", "mantener")); v_modelo = tk.StringVar(value=cfg["modelo"])
    v_estilo = tk.StringVar(value=cfg["estilo"]); v_son = tk.BooleanVar(value=cfg["sonidos"]); v_ini = tk.BooleanVar(value=cfg["inicio_windows"])
    r = 0
    def row(lbl, widget):
        nonlocal r; ttk.Label(f, text=lbl).grid(row=r, column=0, sticky="w", pady=4); widget.grid(row=r, column=1, sticky="we", pady=4); r += 1
    mf = ttk.Frame(f)
    ttk.Radiobutton(mf, text="Local (sin internet, privado)", variable=v_modo, value="local").pack(anchor="w")
    ttk.Radiobutton(mf, text="Online con Groq (gratis, más rápido y preciso)", variable=v_modo, value="online").pack(anchor="w")
    row("Motor:", mf)
    row("Clave API de Groq:", ttk.Entry(f, textvariable=v_key, width=44, show="•"))
    lnk = ttk.Label(f, text="➜ Obtener clave gratis en console.groq.com/keys", foreground="blue", cursor="hand2")
    lnk.bind("<Button-1>", lambda e: __import__("webbrowser").open("https://console.groq.com/keys")); lnk.grid(row=r, column=1, sticky="w"); r += 1
    row("Modelo local:", ttk.Combobox(f, textvariable=v_modelo, state="readonly",
        values=["base", "small", "medium", "large-v3-turbo"], width=20))
    ttk.Label(f, text="base ≈150 MB (rápido) · small ≈480 MB (recomendado) · medium ≈1,5 GB · large-v3-turbo ≈1,6 GB",
              foreground="#555").grid(row=r, column=1, sticky="w"); r += 1
    row("Atajo de teclado:", ttk.Entry(f, textvariable=v_atajo, width=24))
    row("Uso del atajo:", ttk.Combobox(f, textvariable=v_tecla, state="readonly", values=["mantener", "alternar"], width=20))
    ttk.Label(f, text="mantener = mantené apretado mientras hablás · alternar = 1 toque empieza, otro termina",
              foreground="#555").grid(row=r, column=1, sticky="w"); r += 1
    row("", ttk.Checkbutton(f, text="Pulir texto (quitar muletillas, puntuación)", variable=v_pulir))
    row("Estilo (online):", ttk.Combobox(f, textvariable=v_estilo, state="readonly", values=list(ESTILOS), width=20))
    row("", ttk.Checkbutton(f, text="Sonidos al empezar/terminar", variable=v_son))
    row("", ttk.Checkbutton(f, text="Iniciar con Windows", variable=v_ini))
    def ok():
        old_model = cfg["modelo"]
        cfg.update(modo=v_modo.get(), groq_key=v_key.get().strip(), pulir=v_pulir.get(), atajo=v_atajo.get().strip().lower() or "ctrl+alt+space",
                   modo_tecla=v_tecla.get(), modelo=v_modelo.get(), estilo=v_estilo.get(), sonidos=v_son.get(), inicio_windows=v_ini.get())
        if cfg["modo"] == "online" and not cfg["groq_key"]:
            messagebox.showwarning(APP, "Para el modo online necesitás pegar tu clave de Groq. Mientras tanto uso el modo local.", parent=w)
        save(); set_autostart(cfg["inicio_windows"])
        try: register_hotkey()
        except Exception as e:
            messagebox.showerror(APP, f"Atajo inválido: {e}", parent=w); return
        if old_model != cfg["modelo"]:
            global _model; _model = None
        if cfg["modo"] == "local" or not cfg["groq_key"]:
            threading.Thread(target=local_model, daemon=True).start()
        w.destroy()
    ttk.Button(f, text="Guardar", command=ok).grid(row=r, column=1, sticky="e", pady=(10, 0))

def main():
    global tray
    m = ctypes.windll.kernel32.CreateMutexW(None, False, "DictadoLibreMutex")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(0, "Dictado Libre ya está abierto (mirá el ícono junto al reloj).", APP, 0x40); return
    try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AUMID)
    except Exception: pass
    root = tk.Tk(); root.withdraw()
    def poll():
        while not ui_q.empty():
            what = ui_q.get()
            if what == "cfg": settings_window(root)
            elif what == "quit": root.quit()
        root.after(150, poll)
    menu = pystray.Menu(pystray.MenuItem(f"Dictado Libre v{VERSION}", None, enabled=False),
                        pystray.MenuItem(lambda i: f"Instalar actualización v{update['ver']}", lambda: threading.Thread(target=install_update, daemon=True).start(),
                                         visible=lambda i: bool(update["url"])),
                        pystray.MenuItem("Buscar actualizaciones", lambda: threading.Thread(target=check_update, args=(True,), daemon=True).start()),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("Configuración", lambda: ui_q.put("cfg"), default=True),
                        pystray.MenuItem("Abrir registro de errores", lambda: os.startfile(LOG) if os.path.exists(LOG) else None),
                        pystray.MenuItem("Salir", lambda: (tray.stop(), ui_q.put("quit"))))
    tray = pystray.Icon("DictadoLibre", make_icon("cargando"), APP, menu)
    tray.run_detached()
    register_hotkey()
    threading.Thread(target=update_loop, daemon=True).start()
    if cfg["modo"] == "local" or not cfg["groq_key"]:
        threading.Thread(target=local_model, daemon=True).start()
    else: set_state("listo", "listo")
    if cfg["primera_vez"]:
        cfg["primera_vez"] = False; save(); ui_q.put("cfg")
        messagebox.showinfo(APP, f"¡Bienvenido!\n\nMantené apretado {cfg['atajo'].upper()} mientras hablás y soltá: el texto aparece donde esté el cursor.\n\n"
                            "La primera vez se descarga el modelo de voz (≈480 MB), puede tardar unos minutos. El ícono gris = cargando, verde = listo, rojo = escuchando.\n\n"
                            "Opcional: pegá una clave gratis de Groq para el modo online (más rápido y con pulido inteligente).")
    root.after(150, poll); root.mainloop()
    try: tray.stop()
    except Exception: pass
    os._exit(0)

if __name__ == "__main__":
    try: main()
    except Exception as e:
        log("fatal", repr(e)); raise
