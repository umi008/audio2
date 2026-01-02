import asyncio
import websockets
import json
import base64
import pyaudio
import sys
import time
from datetime import datetime
from config import get_settings

settings = get_settings()

# AUDIO
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 24000
CHUNK = 2048

if not settings.OPENAI_API_KEY:
    print("Error: Falta OPENAI_API_KEY")
    sys.exit(1)

def log_turn_data(timestamp, latency_ms, user_transcript, ai_transcript, usage):
    entry = {
        "timestamp": timestamp,
        "turn_data": {
            "latency_ms": latency_ms,
            "user_transcript": user_transcript,
            "ai_transcript": ai_transcript,
            "usage": usage
        }
    }
    try:
        with open(settings.log_file_with_timestamp, "a", encoding="utf-8") as f:
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
                            input_device_index=settings.MIC_INDEX, frames_per_buffer=CHUNK)
        speaker_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True,
                                output_device_index=settings.SPEAKER_INDEX, frames_per_buffer=CHUNK)
    except Exception as e:
        print(f"❌ Error de Hardware: {e}")
        return
    
    headers = {
        "Authorization": "Bearer " + settings.OPENAI_API_KEY,
        "OpenAI-Beta": "realtime=v1"
    }

    async with websockets.connect(settings.MODEL_URL, additional_headers=headers) as ws:
        print("✅ CONECTADO.\n")
        prompt = get_prompt(settings.PROMPT_FILE) if settings.PROMPT_FILE else ""
        session_config = {
            "modalities": ["audio", "text"],
            "input_audio_format": "pcm16",
            "input_audio_transcription": {
                "model": "gpt-4o-transcribe"
                # "prompt": "",  # Opcional
                # "language": "" # Opcional
            },
            "voice": settings.VOICE,
            "instructions": prompt,
            "turn_detection": {
                "type": "server_vad",
                "threshold": settings.THRESHOLD,
                "prefix_padding_ms": settings.PREFIX_PADDING_MS,
                "silence_duration_ms": settings.SILENCE_DURATION_MS,
                "create_response": True,
                "interrupt_response": False
            },
            "input_audio_noise_reduction": {
                "type": "near_field" # Opciones: near_field, far_field, none
            },
            #"include": [ 
                #"item.input_audio_transcription.logprobs",
                #],| null
        }
        
        await ws.send(json.dumps({"type": "session.update", "session": session_config}))
        
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        # --- VARIABLES DE ESTADO PARA LOGGING DE TURNO ---
        ai_is_speaking = False
        turn_start_timestamp = None
        user_transcript = None
        ai_transcript = None
        usage_data = None
        latency_ms = None

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
                        ai_transcript = data['transcript']
                        print(f"🤖 AI: {ai_transcript}")

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        user_transcript = data['transcript']
                        turn_start_timestamp = datetime.now().isoformat()
                        print(f"📝 Tú: {user_transcript}")

                    # 4. LA IA TERMINÓ LA RESPUESTA (Desbloqueamos micro)
                    elif event_type == "response.done":
                        ai_is_speaking = False
                        print("🎤 Turno terminado. Puedes hablar ahora.\n")
                        # Captura datos de uso y latencia si existen
                        usage_data = data.get("usage")
                        if usage_data is None:
                            usage_data = data.get("item", {}).get("usage")
                        if usage_data is None:
                            usage_data = data.get("response", {}).get("usage")
                        # Si sigue siendo None, asigna valores por defecto
                        if usage_data is None:
                            usage_data = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                        if turn_start_timestamp:
                            dt_start = datetime.fromisoformat(turn_start_timestamp)
                            dt_end = datetime.now()
                            latency_ms = (dt_end - dt_start).total_seconds() * 1000
                        else:
                            latency_ms = None
                        log_turn_data(
                            datetime.now().isoformat(),
                            latency_ms,
                            user_transcript,
                            ai_transcript,
                            usage_data
                        )
                        # Reset variables de estado
                        turn_start_timestamp = None
                        user_transcript = None
                        ai_transcript = None
                        usage_data = None
                        latency_ms = None

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
        print("\nFin")