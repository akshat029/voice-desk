# VoiceDesk 🎙️

VoiceDesk is a highly responsive, privacy-conscious, voice-controlled desktop automation agent. It acts as your personal "Jarvis", continuously listening to your voice in the background, analyzing screen context (vision), and controlling your mouse, keyboard, and applications to fulfill complex requests.

## 🚀 Features

- **Zero-Latency Voice Recognition**: Captures audio and transcribes it instantly. Supports both local execution (`faster-whisper`) and ultra-fast cloud transcription (`whisper-large-v3-turbo` via Groq) for near-instant precision.
- **Dynamic Multi-Backend LLM**: Fluidly hot-swap your AI "brain" with a single voice command (e.g. *"Switch to Gemini"*):
  - **Groq Backend**: Ultra-low latency and completely free text inference using `llama-3.3-70b-versatile`.
  - **Gemini Backend**: State-of-the-art vision-language modeling. Google Gemini 2.5 Flash acts as VoiceDesk's eyes to see boundaries and exact XY coordinates of GUI elements.
  - **Ollama Backend**: Absolute privacy. Execute all reasoning locally without internet access.
- **Contextual Memory**: VoiceDesk maintains recent chat history so you can ask follow-up questions referencing previous conversational context.
- **Safety Confirmations**: Destructive behaviors (e.g. `Ctrl + W`, `Alt + F4`, `Delete`) are automatically flagged. The agent will freeze, ask you aloud *"Are you sure?"*, and await your verbal consent before executing.
- **Vision Integration**: On supported backends, automatically captures screenshots using lightweight `mss` alongside `pytesseract` to understand screen state.
- **Fluid TTS Feedback**: Conversational Text-to-Speech replies generated in parallel with Python automation scripts.

## 🛠️ Architecture

VoiceDesk uses a modular architecture entirely independent of bloated agent frameworks:
* **`listener.py`** -> Robust VAD (Voice Activity Detection) microphone continuous capture loop.
* **`brain.py`** -> Assembles context (memory + OCR + vision), formats the system logic, and fetches the JSON action plan from the active AI.
* **`vision.py`** -> Grabs and analyzes the screen state.
* **`executor.py`** -> Validates LLM outputs and fires `PyAutoGUI` hooks and OS application commands.

## 📦 Installation

VoiceDesk requires Python 3.10+ and a few system dependencies.

1. **Clone the repo**
   ```bash
   git clone https://github.com/your-username/VoiceDesk.git
   cd VoiceDesk
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Tesseract OCR** (For Windows Users)
   Download and install [Tesseract-OCR](https://github.com/UB-Mannheim/tesseract/wiki). By default, VoiceDesk expects the binary in your PATH or in `C:\Program Files\Tesseract-OCR\tesseract.exe`.

4. **Environment Setup**
   ```bash
   cp .env.example .env
   ```
   Open `.env` and configure your API keys (Groq & Gemini are both free!). 

## ⚡ Quick Start

After setting your keys in `.env`, just run:
```bash
python main.py
```

Talk to it! Try saying:
* *"Open Chrome."*
* *"What do you see on my screen?"*
* *"Switch to Gemini."*
* *"Close this window for me."*

## 🔒 Privacy & Safety First
If you select `LLM_BACKEND=ollama` and `STT_BACKEND=local`, your data **never** leaves your computer. If you switch to the cloud APIs, only explicitly triggered interaction chunks (`audio.wav` or base64 screenshots) are pushed for rapid analysis.

All actions are logged meticulously in `voicedesk.log`.
