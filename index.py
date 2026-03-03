#!/usr/bin/env python3
"""
Jarvis desktop assistant with GUI + voice support.
Includes dedicated “open <app>” commands for every app listed by the user.
Tested on Windows 11 / Python 3.10+.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import queue
import random
import re
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote_plus

import psutil
import pyttsx3
import requests
import speech_recognition as sr

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    import wikipedia
    wikipedia.set_lang("en")
except Exception:
    wikipedia = None

# ---------- Files & configuration ----------
BASE_DIR = Path(__file__).parent
NOTES_FILE = BASE_DIR / "jarvis_notes.txt"
TODO_FILE = BASE_DIR / "jarvis_todos.txt"
for path in (NOTES_FILE, TODO_FILE):
    path.touch(exist_ok=True)

POMODORO_STATE = {"active": False, "end": None}
VOICE_MODE = True
LISTEN_TIMEOUT = 5
PHRASE_TIME_LIMIT = 6
IS_WINDOWS = platform.system().lower().startswith("win")

# GUI logging pipe
LOG_QUEUE: "queue.Queue[str]" = queue.Queue()

# ---------- Speech / recognition ----------
engine = pyttsx3.init()
engine.setProperty("rate", 175)
voices = engine.getProperty("voices")
if voices:
    engine.setProperty("voice", voices[min(1, len(voices) - 1)].id)

recognizer = sr.Recognizer()


def enqueue_log(text: str) -> None:
    LOG_QUEUE.put(text)


def speak(text: str) -> None:
    enqueue_log(f"JARVIS ➜ {text}")
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as exc:
        enqueue_log(f"(Speech issue: {exc})")


def listen() -> str | None:
    if not VOICE_MODE:
        return None
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            enqueue_log("🎙 Listening...")
            audio = recognizer.listen(
                source, timeout=LISTEN_TIMEOUT, phrase_time_limit=PHRASE_TIME_LIMIT
            )
        query = recognizer.recognize_google(audio, language="en-US")
        enqueue_log(f"👂 Heard: {query}")
        return query.lower().strip()
    except sr.WaitTimeoutError:
        enqueue_log("…No speech detected.")
        return None
    except sr.UnknownValueError:
        speak("I heard something, but I’m not sure what it was.")
        return None
    except sr.RequestError:
        speak("Speech recognition service is unavailable right now.")
        return None
    except Exception as exc:
        speak(f"Microphone issue: {exc}")
        return None


# ---------- Helpers ----------
@dataclass
class Command:
    name: str
    keywords: tuple[str, ...]
    action: Callable[[str], None]
    description: str


COMMANDS: list[Command] = []


def register_command(
    name: str, keywords: Iterable[str], action: Callable[[str], None], description: str
) -> None:
    COMMANDS.append(
        Command(
            name=name,
            keywords=tuple(k.lower() for k in keywords),
            action=action,
            description=description,
        )
    )


def extract_after_keywords(query: str, triggers: Iterable[str]) -> str:
    for trigger in triggers:
        if trigger in query:
            return query.split(trigger, 1)[1].strip()
    return ""


def open_site(url: str, label: str) -> None:
    try:
        webbrowser.open(url, new=2)
        speak(f"Opening {label}.")
    except Exception as exc:
        speak(f"I couldn't open {label}: {exc}")


def require_pyautogui(feature: str) -> bool:
    if pyautogui is None:
        speak(f"PyAutoGUI is missing, so I can’t {feature} right now.")
        return False
    return True


def safe_path(prefix: str, suffix: str = ".png") -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return BASE_DIR / f"{prefix}_{stamp}{suffix}"


def read_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_line(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text.strip() + os.linesep)


def overwrite(path: Path) -> None:
    path.write_text("", encoding="utf-8")


def minutes_left(end_time: dt.datetime | None) -> int:
    if not end_time:
        return 0
    delta = end_time - dt.datetime.now()
    return max(0, int(delta.total_seconds() // 60))


# ---------- Core actions ----------
def tell_time(_: str) -> None:
    speak(f"The time is {dt.datetime.now().strftime('%I:%M %p')}.")


def tell_date(_: str) -> None:
    speak(f"Today is {dt.datetime.now().strftime('%A, %B %d, %Y')}.")


def tell_day(_: str) -> None:
    speak(f"It’s {dt.datetime.now().strftime('%A')}.")


def battery_status(_: str) -> None:
    battery = psutil.sensors_battery()
    if not battery:
        speak("I can't detect a battery on this system.")
        return
    status = "charging" if battery.power_plugged else "discharging"
    speak(f"Battery at {battery.percent:.0f} percent and {status}.")


def cpu_usage(_: str) -> None:
    speak(f"CPU usage is {psutil.cpu_percent(interval=1):.0f} percent.")


def memory_usage(_: str) -> None:
    speak(f"Memory usage is {psutil.virtual_memory().percent:.0f} percent.")


def disk_usage(_: str) -> None:
    target = Path.home().anchor or "/"
    speak(f"Drive usage on {target} is {psutil.disk_usage(target).percent:.0f} percent.")


def system_summary(_: str) -> None:
    info = f"{platform.system()} {platform.release()} ({platform.machine()})"
    speak(f"This computer is running {info}.")


def public_ip(_: str) -> None:
    try:
        ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        speak(f"Your public IP is {ip}.")
    except requests.RequestException:
        speak("I couldn't retrieve the public IP address.")


def google_search(query: str) -> None:
    term = extract_after_keywords(
        query, ("search google for", "google search", "search for")
    )
    if not term:
        speak("Please say something like 'search Google for Python decorators'.")
        return
    open_site(
        f"https://www.google.com/search?q={quote_plus(term)}",
        f"Google results for {term}",
    )


def add_note(query: str) -> None:
    text = extract_after_keywords(query, ("add note", "note that", "remember that"))
    if not text:
        speak("Please include the note text, e.g., 'add note buy milk'.")
        return
    append_line(NOTES_FILE, text)
    speak("Note added.")


def read_notes(_: str) -> None:
    notes = read_lines(NOTES_FILE)
    if not notes:
        speak("Your notebook is empty.")
        return
    speak("Here are your notes:")
    for idx, line in enumerate(notes, 1):
        speak(f"Note {idx}: {line}")


def clear_notes(_: str) -> None:
    overwrite(NOTES_FILE)
    speak("All notes cleared.")


def add_todo(query: str) -> None:
    item = extract_after_keywords(query, ("add todo", "new todo", "remember to"))
    if not item:
        speak("Try saying 'add todo submit report'.")
        return
    append_line(TODO_FILE, item)
    speak("Task added to your list.")


def list_todos(_: str) -> None:
    todos = read_lines(TODO_FILE)
    if not todos:
        speak("Your to-do list is empty.")
        return
    speak("Here is your to-do list.")
    for idx, line in enumerate(todos, 1):
        speak(f"Task {idx}: {line}")


def clear_todos(_: str) -> None:
    overwrite(TODO_FILE)
    speak("Your to-do list is now clear.")


def start_pomodoro(_: str) -> None:
    if POMODORO_STATE["active"]:
        speak(
            f"A pomodoro is already running with {minutes_left(POMODORO_STATE['end'])} minutes left."
        )
        return
    end_time = dt.datetime.now() + dt.timedelta(minutes=25)
    POMODORO_STATE.update({"active": True, "end": end_time})
    speak("Pomodoro started for 25 minutes. I’ll let you know when time is up.")


def stop_pomodoro(_: str) -> None:
    if not POMODORO_STATE["active"]:
        speak("No pomodoro timer is running.")
        return
    POMODORO_STATE.update({"active": False, "end": None})
    speak("Pomodoro stopped. Nice hustle!")


PRODUCTIVITY_TIPS = [
    "Group similar tasks to stay in flow.",
    "Protect your focus with short, dedicated sprints.",
    "Plan tomorrow before you finish today.",
    "Use keyboard shortcuts; tiny gains add up.",
    "Break daunting goals into micro-steps.",
]


def random_tip(_: str) -> None:
    speak(f"Tip: {random.choice(PRODUCTIVITY_TIPS)}")


def list_commands(_: str) -> None:
    speak(f"I know {len(COMMANDS)} commands. Check the console for details.")
    for idx, cmd in enumerate(COMMANDS, 1):
        print(f"{idx:>3}. {cmd.name:<32} | {cmd.description}")


def lock_workstation(_: str) -> None:
    if not IS_WINDOWS:
        speak("Locking is configured for Windows only.")
        return
    try:
        import ctypes

        ctypes.windll.user32.LockWorkStation()
        speak("Locking the workstation. See you soon.")
    except Exception as exc:
        speak(f"I couldn't lock the workstation: {exc}")


def show_desktop(_: str) -> None:
    if not require_pyautogui("show the desktop"):
        return
    pyautogui.hotkey("win", "d")
    speak("Desktop displayed.")


def minimize_all(_: str) -> None:
    if not require_pyautogui("minimize windows"):
        return
    pyautogui.hotkey("win", "m")
    speak("Windows minimized.")


def new_virtual_desktop(_: str) -> None:
    if not require_pyautogui("create a virtual desktop"):
        return
    pyautogui.hotkey("win", "ctrl", "d")
    speak("New virtual desktop created.")


def next_desktop(_: str) -> None:
    if not require_pyautogui("switch desktops"):
        return
    pyautogui.hotkey("win", "ctrl", "right")
    speak("Switched to the next desktop.")


def previous_desktop(_: str) -> None:
    if not require_pyautogui("switch desktops"):
        return
    pyautogui.hotkey("win", "ctrl", "left")
    speak("Switched to the previous desktop.")


def close_window(_: str) -> None:
    if not require_pyautogui("close the current window"):
        return
    pyautogui.hotkey("alt", "f4")
    speak("Closed the active window.")


def take_screenshot(_: str) -> None:
    if not require_pyautogui("take a screenshot"):
        return
    path = safe_path("screenshot")
    pyautogui.screenshot().save(path)
    speak(f"Screenshot saved to {path.name}.")


def volume_up(_: str) -> None:
    if not require_pyautogui("adjust volume"):
        return
    pyautogui.press("volumeup")
    speak("Volume turned up.")


def volume_down(_: str) -> None:
    if not require_pyautogui("adjust volume"):
        return
    pyautogui.press("volumedown")
    speak("Volume turned down.")


JOKES = [
    "I told my computer I needed a break, and it said no problem—it will go to sleep.",
    "Debugging is like being the detective in a crime movie where you are also the murderer.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
]
FUN_FACTS = [
    "Honey never spoils; archaeologists have tasted jars from ancient tombs.",
    "Octopuses have three hearts.",
    "Bananas are berries, but strawberries are not.",
]
QUOTES = [
    "Success is not final, failure is not fatal; it is the courage to continue that counts.",
    "Do something today that your future self will thank you for.",
    "Small progress is still progress.",
]
COMPLIMENTS = [
    "You make tricky tasks look easy.",
    "Your curiosity is downright inspiring.",
    "You bring excellent energy to this project.",
]
ROASTS = [
    "If procrastination were an Olympic sport, you'd finally get gold.",
    "Your to-do list called—it misses you.",
    "You ignore deadlines with such confidence; I'm impressed.",
]
COLORS = ["crimson", "teal", "sunset orange", "midnight blue", "emerald", "lavender"]


def tell_joke(_: str) -> None:
    speak(random.choice(JOKES))


def fun_fact(_: str) -> None:
    speak(random.choice(FUN_FACTS))


def motivational_quote(_: str) -> None:
    speak(random.choice(QUOTES))


def compliment(_: str) -> None:
    speak(random.choice(COMPLIMENTS))


def friendly_roast(_: str) -> None:
    speak(random.choice(ROASTS))


def coin_flip(_: str) -> None:
    speak(f"It's {random.choice(['heads', 'tails'])}.")


def roll_dice(_: str) -> None:
    speak(f"You rolled a {random.randint(1, 6)}.")


def random_number(query: str) -> None:
    numbers = [int(n) for n in re.findall(r"\d+", query)]
    low, high = 1, 100
    if len(numbers) >= 2:
        low, high = sorted(numbers[:2])
    elif len(numbers) == 1:
        high = max(numbers[0], 1)
    result = random.randint(low, high)
    speak(f"Random number between {low} and {high} is {result}.")


def lucky_color(_: str) -> None:
    speak(f"Today's lucky color is {random.choice(COLORS)}.")


def exit_assistant(_: str) -> None:
    speak("Shutting down. Call me anytime!")
    sys.exit(0)


def python_docs(_: str) -> None:
    open_site("https://docs.python.org/3/", "the Python documentation")


def mdn_docs(_: str) -> None:
    open_site("https://developer.mozilla.org/", "MDN Web Docs")


def stackoverflow_search(query: str) -> None:
    term = extract_after_keywords(
        query,
        (
            "stack overflow search for",
            "search stack overflow for",
            "stack overflow search",
        ),
    )
    if not term:
        speak("Please add a topic, e.g., 'stack overflow search for list comprehension'.")
        return
    open_site(
        f"https://stackoverflow.com/search?q={quote_plus(term)}",
        f"Stack Overflow results for {term}",
    )


def wikipedia_summary(query: str) -> None:
    topic = extract_after_keywords(
        query, ("wikipedia summary for", "wikipedia summary", "lookup")
    )
    if not topic:
        speak("Try saying 'Wikipedia summary for Ada Lovelace'.")
        return
    if wikipedia is None:
        speak("The wikipedia module is missing. Install it with 'pip install wikipedia'.")
        return
    try:
        summary = wikipedia.summary(topic, sentences=2)
        speak(summary)
    except wikipedia.exceptions.DisambiguationError as exc:
        speak(f"That topic is ambiguous. Maybe you meant: {', '.join(exc.options[:3])}.")
    except wikipedia.exceptions.PageError:
        speak("I couldn't find that topic on Wikipedia.")
    except Exception as exc:
        speak(f"Wikipedia had a hiccup: {exc}")


def dictionary_definition(query: str) -> None:
    word = extract_after_keywords(query, ("define", "definition of", "dictionary"))
    if not word:
        speak("Please specify a word, like 'define serendipity'.")
        return
    try:
        resp = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=5
        )
        resp.raise_for_status()
        data = resp.json()
        meaning = data[0]["meanings"][0]["definitions"][0]["definition"]
        speak(f"{word} means: {meaning}")
    except requests.RequestException:
        speak("The dictionary service isn't reachable right now.")
    except (KeyError, IndexError):
        speak(f"I couldn't find a definition for {word}.")
    except Exception as exc:
        speak(f"Dictionary error: {exc}")


# ---------- Application launch layer ----------
APP_DEFINITIONS = [
    {"name": "Accessibility", "launcher": {"method": "path", "target": r"C:\Windows\System32\utilman.exe"}},
    {"name": "Adobe Reader", "launcher": {"method": "path", "target": r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe"}},
    {"name": "Al-Quran", "launcher": {"method": "path", "target": r"C:\Program Files\Al-Quran\alquran.exe"}},
    {"name": "Calculator", "launcher": {"method": "aumid", "target": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"}},
    {"name": "Camera", "launcher": {"method": "aumid", "target": "Microsoft.WindowsCamera_8wekyb3d8bbwe!App"}},
    {"name": "ChatGPT", "launcher": {"method": "shortcut", "target": r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\ChatGPT.lnk"}},
    {"name": "Chrome Apps", "launcher": {"method": "shortcut", "target": r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Chrome Apps.lnk"}},
    {"name": "Clock", "launcher": {"method": "aumid", "target": "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App"}},
    {"name": "Copilot", "launcher": {"method": "protocol", "target": "microsoft-copilot://"}},
    {"name": "Family", "launcher": {"method": "aumid", "target": "MicrosoftCorporationII.MicrosoftFamily_8wekyb3d8bbwe!App"}},
    {"name": "Feedback Hub", "launcher": {"method": "aumid", "target": "Microsoft.WindowsFeedbackHub_8wekyb3d8bbwe!App"}},
    {"name": "File Explorer", "launcher": {"method": "command", "target": "explorer.exe"}},
    {"name": "Game Bar", "launcher": {"method": "aumid", "target": "Microsoft.XboxGamingOverlay_8wekyb3d8bbwe!App"}},
    {"name": "Get Help", "launcher": {"method": "aumid", "target": "Microsoft.GetHelp_8wekyb3d8bbwe!App"}},
    {"name": "Get Started", "launcher": {"method": "aumid", "target": "Microsoft.Getstarted_8wekyb3d8bbwe!App"}},
    {"name": "Git", "launcher": {"method": "path", "target": r"C:\Program Files\Git\git-bash.exe"}},
    {"name": "Google Chrome", "launcher": {"method": "path", "target": r"C:\Program Files\Google\Chrome\Application\chrome.exe"}},
    {"name": "Instagram", "launcher": {"method": "aumid", "target": "Facebook.InstagramBeta_8xx8rvfyw5nnt!App"}},
    {"name": "Intel Graphics Software", "launcher": {"method": "aumid", "target": "AppUp.IntelGraphicsExperience_8j3eq9eme6ctt!App"}},
    {"name": "Media Player", "launcher": {"method": "aumid", "target": "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"}},
    {"name": "Microsoft Clipchamp", "launcher": {"method": "aumid", "target": "Clipchamp.Clipchamp_yxz26nhyzhsrt!App"}},
    {"name": "Microsoft Edge", "launcher": {"method": "path", "target": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"}},
    {"name": "Microsoft Store", "launcher": {"method": "aumid", "target": "Microsoft.WindowsStore_8wekyb3d8bbwe!App"}},
    {"name": "Microsoft Teams", "launcher": {"method": "path", "target": r"C:\Users\%USERNAME%\AppData\Local\Microsoft\Teams\Update.exe --processStart Teams.exe"}},
    {"name": "Microsoft To Do", "launcher": {"method": "aumid", "target": "Microsoft.Todos_8wekyb3d8bbwe!App"}},
    {"name": "News", "launcher": {"method": "aumid", "target": "Microsoft.BingNews_8wekyb3d8bbwe!AppexNews"}},
    {"name": "Node.js", "launcher": {"method": "path", "target": r"C:\Program Files\nodejs\node.exe"}},
    {"name": "Notepad", "launcher": {"method": "path", "target": r"C:\Windows\System32\notepad.exe"}},
    {"name": "NVIDIA Control Panel", "launcher": {"method": "command", "target": r"control.exe /name NVIDIA.ControlPanel"}},
    {"name": "OneDrive", "launcher": {"method": "path", "target": r"C:\Users\%USERNAME%\AppData\Local\Microsoft\OneDrive\OneDrive.exe"}},
    {"name": "Outlook", "launcher": {"method": "path", "target": r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE"}},
    {"name": "Paint", "launcher": {"method": "path", "target": r"C:\Windows\System32\mspaint.exe"}},
    {"name": "Phone Link", "launcher": {"method": "aumid", "target": "Microsoft.YourPhone_8wekyb3d8bbwe!App"}},
    {"name": "Photos", "launcher": {"method": "aumid", "target": "Microsoft.Photos_8wekyb3d8bbwe!App"}},
    {"name": "Python 3.10", "launcher": {"method": "path", "target": r"C:\Program Files\Python310\python.exe"}},
    {"name": "Python Installer Manager", "launcher": {"method": "path", "target": r"C:\Users\%USERNAME%\AppData\Local\Programs\Python Launcher\pylauncher.exe"}},
    {"name": "Quick Assist", "launcher": {"method": "aumid", "target": "MicrosoftCorporationII.QuickAssist_8wekyb3d8bbwe!App"}},
    {"name": "Settings", "launcher": {"method": "protocol", "target": "ms-settings:"}},
    {"name": "Snipping Tool", "launcher": {"method": "aumid", "target": "Microsoft.ScreenSketch_8wekyb3d8bbwe!App"}},
    {"name": "Sound Recorder", "launcher": {"method": "aumid", "target": "Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe!App"}},
    {"name": "Sticky Notes", "launcher": {"method": "aumid", "target": "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App"}},
    {"name": "Terminal", "launcher": {"method": "path", "target": r"C:\Windows\System32\wt.exe"}},
    {"name": "UltraViewer", "launcher": {"method": "path", "target": r"C:\Program Files\UltraViewer\UltraViewer.exe"}},
    {"name": "VideoLAN", "launcher": {"method": "path", "target": r"C:\Program Files\VideoLAN\VLC\vlc.exe"}},
    {"name": "Visual Studio Code", "launcher": {"method": "path", "target": r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe"}},
    {"name": "Weather", "launcher": {"method": "aumid", "target": "Microsoft.BingWeather_8wekyb3d8bbwe!App"}},
    {"name": "WhatsApp", "launcher": {"method": "aumid", "target": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"}},
    {"name": "Windows Backup", "launcher": {"method": "aumid", "target": "Microsoft.WindowsBackup_8wekyb3d8bbwe!App"}},
    {"name": "Windows Security", "launcher": {"method": "command", "target": "windowsdefender://"}},
    {"name": "Windows Tool", "launcher": {"method": "path", "target": r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Administrative Tools.lnk"}},
    {"name": "WinRAR", "launcher": {"method": "path", "target": r"C:\Program Files\WinRAR\WinRAR.exe"}},
    {"name": "Xbox", "launcher": {"method": "aumid", "target": "Microsoft.GamingApp_8wekyb3d8bbwe!App"}},
]


def expand_env_path(path: str) -> str:
    return os.path.expandvars(path)


def launch_application(app_id: str) -> None:
    meta = APP_LAUNCHERS[app_id]
    launcher = meta["launcher"]
    method = launcher["method"]
    target = expand_env_path(launcher["target"])
    try:
        if method == "path":
            exe_path = Path(target)
            if not exe_path.exists():
                speak(
                    f"I couldn't find {meta['name']} at {exe_path}. Please update APP_DEFINITIONS."
                )
                return
            subprocess.Popen([str(exe_path)], shell=False)
        elif method == "shortcut":
            shortcut = Path(target)
            if not shortcut.exists():
                speak(
                    f"The shortcut for {meta['name']} wasn't found. Update APP_DEFINITIONS."
                )
                return
            os.startfile(str(shortcut))
        elif method == "aumid":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])
        elif method == "command":
            subprocess.Popen(target, shell=True)
        elif method == "protocol":
            os.startfile(target)
        else:
            speak(f"Unknown launch method for {meta['name']}.")
            return
        speak(f"Opening {meta['name']}.")
    except Exception as exc:
        speak(f"{meta['name']} refused to open: {exc}")


APP_LAUNCHERS: dict[str, dict] = {}


def register_application_commands() -> None:
    for definition in APP_DEFINITIONS:
        slug = definition["name"].lower().replace(" ", "_")
        meta = {
            "name": definition["name"],
            "launcher": definition["launcher"],
        }
        APP_LAUNCHERS[slug] = meta

        base = definition["name"].lower()
        aliases = {base, base.replace(" ", ""), base.replace(" ", "-")}
        keywords = []
        for alias in aliases:
            keywords.extend(
                (
                    f"open {alias}",
                    f"launch {alias}",
                    f"start {alias}",
                )
            )
        register_command(
            name=f"open_{slug}",
            keywords=keywords,
            action=lambda _q, app_key=slug: launch_application(app_key),
            description=f"Launch {definition['name']}.",
        )


# ---------- Command registration ----------
def build_commands() -> None:
    COMMANDS.clear()

    # Core info
    register_command("time", ("what time", "current time"), tell_time, "Tell current time.")
    register_command("date", ("what date", "current date"), tell_date, "Tell today's date.")
    register_command("day", ("what day", "current day"), tell_day, "Tell day of week.")
    register_command("battery_status", ("battery status", "battery level"), battery_status, "Report battery level.")
    register_command("cpu_usage", ("cpu usage", "processor usage"), cpu_usage, "Report CPU usage.")
    register_command("memory_usage", ("memory usage", "ram usage"), memory_usage, "Report RAM usage.")
    register_command("disk_usage", ("disk usage", "drive usage"), disk_usage, "Report disk usage.")
    register_command("system_summary", ("system info", "system summary"), system_summary, "System information.")
    register_command("public_ip", ("public ip", "ip address"), public_ip, "Fetch public IP.")
    register_command("google_search", ("search google for", "google search"), google_search, "Search Google.")

    # Productivity
    register_command("add_note", ("add note", "note that"), add_note, "Append a note.")
    register_command("read_notes", ("read notes", "show notes"), read_notes, "Read notes.")
    register_command("clear_notes", ("clear notes", "delete notes"), clear_notes, "Clear notes.")
    register_command("add_todo", ("add todo", "new todo"), add_todo, "Add task.")
    register_command("list_todos", ("list todos", "show todos"), list_todos, "Read tasks.")
    register_command("clear_todos", ("clear todos", "delete todos"), clear_todos, "Clear tasks.")
    register_command("start_pomodoro", ("start pomodoro", "focus timer"), start_pomodoro, "Start Pomodoro.")
    register_command("stop_pomodoro", ("stop pomodoro", "end pomodoro"), stop_pomodoro, "Stop Pomodoro.")
    register_command("list_commands", ("list commands", "help menu"), list_commands, "List all commands.")
    register_command("productivity_tip", ("productivity tip", "motivate me"), random_tip, "Share tip.")

    # Window controls
    register_command("lock_pc", ("lock pc", "lock workstation"), lock_workstation, "Lock Windows session.")
    register_command("show_desktop", ("show desktop",), show_desktop, "Show desktop.")
    register_command("minimize_all", ("minimize all",), minimize_all, "Minimize windows.")
    register_command("new_desktop", ("new desktop", "create desktop"), new_virtual_desktop, "Create virtual desktop.")
    register_command("next_desktop", ("next desktop", "switch desktop right"), next_desktop, "Next desktop.")
    register_command("previous_desktop", ("previous desktop", "switch desktop left"), previous_desktop, "Prev desktop.")
    register_command("close_window", ("close window", "close app"), close_window, "Close active window.")
    register_command("take_screenshot", ("take screenshot", "capture screen"), take_screenshot, "Save screenshot.")
    register_command("volume_up", ("volume up", "increase volume"), volume_up, "Volume up.")
    register_command("volume_down", ("volume down", "decrease volume"), volume_down, "Volume down.")

    # Fun extras
    register_command("tell_joke", ("tell a joke", "joke"), tell_joke, "Tell a joke.")
    register_command("fun_fact", ("fun fact", "random fact"), fun_fact, "Share fun fact.")
    register_command("motivational_quote", ("motivate me", "give me a quote"), motivational_quote, "Motivational quote.")
    register_command("compliment", ("compliment me",), compliment, "Give compliment.")
    register_command("friendly_roast", ("roast me", "friendly roast"), friendly_roast, "Playful roast.")
    register_command("coin_flip", ("flip a coin",), coin_flip, "Flip coin.")
    register_command("roll_dice", ("roll a die", "roll dice"), roll_dice, "Roll d6.")
    register_command("random_number", ("random number", "pick a number"), random_number, "Random number.")
    register_command("lucky_color", ("lucky color", "color of the day"), lucky_color, "Lucky color.")
    register_command("exit", ("exit", "quit", "goodbye"), exit_assistant, "Exit assistant.")

    # Knowledge
    register_command("python_docs", ("open python docs", "python documentation"), python_docs, "Open Python docs.")
    register_command("mdn_docs", ("open mdn", "mdn docs"), mdn_docs, "Open MDN.")
    register_command("stackoverflow_search", ("stack overflow search",), stackoverflow_search, "Search Stack Overflow.")
    register_command("wikipedia_summary", ("wikipedia summary", "lookup on wikipedia"), wikipedia_summary, "Wikipedia summary.")
    register_command("dictionary_definition", ("define", "dictionary"), dictionary_definition, "Define word.")

    # Application launchers (user list)
    register_application_commands()


# ---------- Command processing ----------
def handle_query(raw_query: str) -> None:
    query = raw_query.lower().strip()
    if not query:
        return
    for command in COMMANDS:
        if any(keyword in query for keyword in command.keywords):
            command.action(query)
            return
    speak("Sorry, I don't recognize that command yet.")


def check_pomodoro() -> None:
    if POMODORO_STATE["active"] and POMODORO_STATE["end"] and dt.datetime.now() >= POMODORO_STATE["end"]:
        POMODORO_STATE.update({"active": False, "end": None})
        speak("Pomodoro complete! Time for a well-deserved break.")


# ---------- GUI ----------
def flush_log(widget) -> None:
    try:
        while True:
            msg = LOG_QUEUE.get_nowait()
            widget.configure(state="normal")
            widget.insert("end", msg + "\n")
            widget.configure(state="disabled")
            widget.see("end")
    except queue.Empty:
        pass


class JarvisDesktopApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import scrolledtext

        self.tk = tk
        self.root = tk.Tk()
        self.root.title("Jarvis Assistant")
        self.root.geometry("720x520")
        self.root.protocol("WM_DELETE_WINDOW", self.safe_close)

        self.console = scrolledtext.ScrolledText(self.root, state="disabled", wrap="word")
        self.console.pack(fill="both", expand=True, padx=12, pady=12)

        control_frame = tk.Frame(self.root)
        control_frame.pack(fill="x", padx=12, pady=(0, 12))

        self.voice_var = tk.BooleanVar(value=True)

        self.start_btn = tk.Button(control_frame, text="Start Listening", command=self.start_voice)
        self.start_btn.pack(side="left", padx=4)

        self.stop_btn = tk.Button(control_frame, text="Stop Listening", command=self.stop_voice)
        self.stop_btn.pack(side="left", padx=4)

        tk.Checkbutton(
            control_frame, text="Enable voice replies", variable=self.voice_var, command=self.toggle_voice_output
        ).pack(side="left", padx=12)

        self.entry = tk.Entry(control_frame)
        self.entry.pack(side="left", fill="x", expand=True, padx=4)
        self.entry.bind("<Return>", lambda _event: self.run_entry())

        tk.Button(control_frame, text="Send", command=self.run_entry).pack(side="left", padx=4)

        tk.Button(control_frame, text="List commands", command=lambda: handle_query("list commands")).pack(side="left", padx=4)

        self.voice_thread: threading.Thread | None = None
        self.voice_stop_event = threading.Event()

        self.root.after(100, self.gui_tick)
        self.root.after(1000, self.pomodoro_tick)

        enqueue_log("Jarvis GUI ready. Click 'Start Listening' or type a command.")

    def gui_tick(self) -> None:
        flush_log(self.console)
        self.root.after(100, self.gui_tick)

    def pomodoro_tick(self) -> None:
        check_pomodoro()
        self.root.after(1000, self.pomodoro_tick)

    def toggle_voice_output(self) -> None:
        global VOICE_MODE
        # Voice replies (TTS) remain on; this toggle just informs user
        enqueue_log("Voice replies turned " + ("on." if self.voice_var.get() else "off (but text still shows)."))

    def start_voice(self) -> None:
        global VOICE_MODE
        if self.voice_thread and self.voice_thread.is_alive():
            enqueue_log("Voice listener already running.")
            return
        VOICE_MODE = True
        self.voice_stop_event.clear()
        self.voice_thread = threading.Thread(target=self.voice_loop, daemon=True)
        self.voice_thread.start()
        enqueue_log("Voice listener started.")

    def stop_voice(self) -> None:
        global VOICE_MODE
        VOICE_MODE = False
        self.voice_stop_event.set()
        enqueue_log("Voice listener stopping...")

    def voice_loop(self) -> None:
        while not self.voice_stop_event.is_set():
            query = listen()
            if query:
                handle_query(query)

    def run_entry(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        enqueue_log(f"YOU ➜ {text}")
        self.entry.delete(0, "end")
        handle_query(text)

    def safe_close(self) -> None:
        self.stop_voice()
        self.root.after(300, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


# ---------- Main ----------
def cli_loop() -> None:
    speak("Jarvis online. Type or speak commands. Ctrl+C to exit.")
    try:
        while True:
            check_pomodoro()
            query = listen()
            if not query:
                query = input("Type a command (or press Enter to retry voice): ").strip().lower()
                if not query:
                    continue
            handle_query(query)
    except KeyboardInterrupt:
        speak("Shutting down. Catch you later!")
    except SystemExit:
        pass
    except Exception as exc:
        speak(f"Unexpected error: {exc}")


def gui_loop() -> None:
    app = JarvisDesktopApp()
    app.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis desktop assistant")
    parser.add_argument("--cli", action="store_true", help="Run in terminal mode instead of GUI.")
    args = parser.parse_args()

    build_commands()
    speak(f"Command inventory loaded: {len(COMMANDS)} items.")

    if args.cli:
        cli_loop()
    else:
        gui_loop()


if __name__ == "__main__":
    main()