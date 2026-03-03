Jarvis Desktop Assistant (Python GUI + Voice Automation)

A personal AI-powered desktop assistant built in Python, capable of voice commands, system automation, app launching, web search, productivity tools, and a full Tkinter GUI.
Designed to help with daily tasks on Windows 11.

This project is fully customizable and built for personal use.

🚀 Features
🎙 Voice Input + Text Commands

Google Speech Recognition

Text-to-Speech (TTS) replies

GUI console logs

Start/Stop voice listener

🧠 Smart Utilities

Time, date, day lookup

Battery, CPU, RAM, Disk usage

Public IP check

System summary

Google, StackOverflow, Wikipedia search

Dictionary API lookup

📝 Notes & Tasks

Add, read, clear notes

Add, list, clear todos

Persistence with local .txt storage

⏱ Productivity Tools

Pomodoro timer with auto reminders

Random productivity tips

Quotes, jokes, facts, roasts

🪟 System Control (Windows)

Lock workstation

Show desktop

Minimize all

Create/switch virtual desktops

Volume controls

Screenshots

📂 App Launcher Layer

Launch installed Windows apps with voice commands like:

"open chrome", "start notepad", "launch vscode"

Apps are defined in APP_DEFINITIONS and include:

Chrome, VS Code, Git Bash

Calculator, Camera

MS Store, Edge, Snipping Tool

WhatsApp, Instagram

VLC, Paint

And many more…

🖼 Full Tkinter GUI

Live log console

Manual command bar

Buttons for voice control

List commands button

🧩 Tech Stack

Python 3.10+

Tkinter (GUI)

pyttsx3 (TTS)

SpeechRecognition + Google API

psutil

requests

pyautogui

wikipedia

📁 Project Structure
jarvis/
│── jarvis_desktop_gui.py      # Main script
│── jarvis_notes.txt           # Auto-created notes
│── jarvis_todos.txt           # Auto-created todos
│── README.md
▶️ How to Run
1. Install dependencies
pip install pyttsx3 SpeechRecognitaion psutil requests pyautogui wikipedia
2. Run the assistant
python jarvis_desktop_gui.py
3. For CLI mode
python jarvis_desktop_gui.py --cli
🧠 Important Notes

This project is built for Windows 11 (most automation shortcuts use Win key).

Make sure microphone permissions are allowed.

If some apps don’t open, update their locations in APP_DEFINITIONS.

📜 License

Free for personal use.
Do not sell commercially without permission.
