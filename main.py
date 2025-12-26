import os
import asyncio
import websockets
import json
import base64
import pyaudio
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURACIÓN ---
API_KEY = os.getenv("OPENAI_API_KEY")
URL = os.getenv("MODEL_URL", "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview")
VOICE = os.getenv("VOICE", "alloy")
MODEL_NAME = os.getenv("MODEL_NAME", "")
SYSTEM_PROMPT_PATH = os.getenv("SYSTEM_PROMPT_PATH", "")
THRESHOLD = float(os.getenv("THRESHOLD", "0.99"))
PREFIX_PADDING_MS = int(os.getenv("PREFIX_PADDING_MS", "300"))
SILENCE_DURATION_MS = int(os.getenv("SILENCE_DURATION_MS", "3000"))

# HARDWARE
MIC_INDEX = 1        
SPEAKER_INDEX = None 

# AUDIO
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 24000
CHUNK = 2048

# NOMBRE DEL ARCHIVO LOG
LOG_FILENAME = f"conversation_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

if not API_KEY:
    print("Error: Falta OPENAI_API_KEY")
    sys.exit(1)

def log_event(event_type, payload):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "timestamp_unix": time.time(),
        "event_type": event_type,
        "data": payload
    }
    try:
        with open(LOG_FILENAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def get_prompt(prompt_path):
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_audio_blocking(stream, chunk):
    return stream.read(chunk, exception_on_overflow=False)

async def realtime_api():
    p = pyaudio.PyAudio()

    try:
        mic_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True,
                            input_device_index=MIC_INDEX, frames_per_buffer=CHUNK)
        speaker_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True,
                                output_device_index=SPEAKER_INDEX, frames_per_buffer=CHUNK)
    except Exception as e:
        print(f"❌ Error de Hardware: {e}")
        return
    
    headers = {
        "Authorization": "Bearer " + API_KEY,
        "OpenAI-Beta": "realtime=v1"
    }

    async with websockets.connect(URL, additional_headers=headers) as ws:
        print("✅ CONECTADO.\n")
        prompt = get_prompt(SYSTEM_PROMPT_PATH) if SYSTEM_PROMPT_PATH else ""
        session_config = {
            "modalities": ["audio", "text"],
            "voice": VOICE,
            "instructions": prompt,
            "turn_detection": {
                "type": "server_vad",
                "threshold": THRESHOLD,
                "prefix_padding_ms": PREFIX_PADDING_MS,
                "silence_duration_ms": SILENCE_DURATION_MS
            }
        }
        
        await ws.send(json.dumps({"type": "session.update", "session": session_config}))
        
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        # --- VARIABLE DE CONTROL DE ESTADO ---
        ai_is_speaking = False

        async def receive_audio():
            nonlocal ai_is_speaking
            
            while not stop_event.is_set():
                try:
                    message = await ws.recv()
                    data = json.loads(message)
                    event_type = data["type"]

                    # 1. LA IA COMIENZA A RESPONDER (Bloqueamos micro)
                    if event_type == "response.created":
                        if not ai_is_speaking:
                            ai_is_speaking = True
                            print("\n🔇 IA hablando - Micrófono silenciado temporalmente...")

                    # 2. AUDIO ENTRANTE
                    elif event_type == "response.audio.delta":
                        # Aseguramos que esté marcado como hablando
                        if not ai_is_speaking: 
                             ai_is_speaking = True
                        
                        audio_chunk = base64.b64decode(data["delta"])
                        speaker_stream.write(audio_chunk)

                    # 3. TRANSCRIPCIONES
                    elif event_type == "response.audio_transcript.done":
                        print(f"🤖 AI: {data['transcript']}")

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        print(f"📝 Tú: {data['transcript']}")

                    # 4. LA IA TERMINÓ LA RESPUESTA (Desbloqueamos micro)
                    elif event_type == "response.done":
                        ai_is_speaking = False
                        print("🎤 Turno terminado. Puedes hablar ahora.\n")
                        log_event("ai_turn_complete", {})

                    elif event_type == "error":
                        print(f"❌ Error: {data['error']['message']}")

                except websockets.exceptions.ConnectionClosed:
                    stop_event.set()
                    break
                except Exception as e:
                    print(f"Error en receive: {e}")
                    break

        async def send_audio():
            print("🎤 MICRO ACTIVADO (Esperando tu voz...)")
            
            while not stop_event.is_set():
                try:
                    # SIEMPRE leemos del hardware para evitar desbordamiento del buffer
                    data = await loop.run_in_executor(None, read_audio_blocking, mic_stream, CHUNK)
                    
                    # LÓGICA DE BLOQUEO:
                    # Si la IA está hablando, ignoramos los datos (continue)
                    # No enviamos nada al socket
                    if ai_is_speaking:
                        continue

                    # Si la IA calla, enviamos audio
                    base64_audio = base64.b64encode(data).decode("utf-8")
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64_audio
                    }))
                except Exception as e:
                    print(f"Error envío: {e}")
                    stop_event.set()
                    break

        await asyncio.gather(receive_audio(), send_audio())

    mic_stream.stop_stream(); mic_stream.close()
    speaker_stream.stop_stream(); speaker_stream.close()
    p.terminate()

if __name__ == "__main__":
    try:
        asyncio.run(realtime_api())
    except KeyboardInterrupt:
        print("\n👋 Fin.")