import asyncio
import websockets
import json
import base64
import sys
from datetime import datetime
from config import get_settings
from audio.manager import AudioManager
from audio.constants import FORMAT, CHANNELS, RATE, CHUNK
from prompts.loader import load_prompt
from logging_modules.conversation_logger import ConversationLogger
from state.conversation_state import ConversationState
from api.session_config import create_session_config
from utils.helpers import read_audio_blocking

settings = get_settings()

if not settings.OPENAI_API_KEY:
    print("Error: Falta OPENAI_API_KEY")
    sys.exit(1)

def log_turn_data(timestamp, ttfb_ms, user_transcript, ai_transcript, usage):
    entry = {
        "timestamp": timestamp,
        "turn_data": {
            "latency_ms": ttfb_ms,
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

async def realtime_api():
    audio_manager = AudioManager()
    try:
        mic_stream = audio_manager.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True,
                                          input_device_index=settings.MIC_INDEX, frames_per_buffer=CHUNK)
        speaker_stream = audio_manager.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True,
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
        with open(settings.PROMPT_FILE, 'r', encoding='utf-8') as f:
            prompt = f.read()
        session_config = {
            "modalities": ["audio", "text"],
            "input_audio_format": "pcm16",
            "input_audio_transcription": {
                "model": "gpt-4o-transcribe"
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
                "type": "near_field"
            },
        }
        await ws.send(json.dumps({"type": "session.update", "session": session_config}))
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        ai_is_speaking = False
        turn_start_timestamp = None
        user_transcript = None
        ai_transcript = None
        usage_data = None
        ttfb_ms = None

        async def receive_audio():
            nonlocal ai_is_speaking, turn_start_timestamp, user_transcript, ai_transcript, usage_data, ttfb_ms
            ttfb_start = None
            first_audio_received = False
            while not stop_event.is_set():
                try:
                    message = await ws.recv()
                    data = json.loads(message)
                    event_type = data["type"]
                    if event_type == "response.created":
                        if not ai_is_speaking:
                            ai_is_speaking = True
                            ttfb_start = datetime.now()
                            print("\n🔇 IA hablando - Micrófono silenciado temporalmente...")
                    elif event_type == "response.audio.delta":
                        if not ai_is_speaking:
                            ai_is_speaking = True
                            if ttfb_start is None:
                                ttfb_start = datetime.now()
                        # Calcular TTFB solo para el primer chunk de audio
                        if not first_audio_received:
                            ttfb_ms = (datetime.now() - ttfb_start).total_seconds() * 1000
                            first_audio_received = True
                        audio_chunk = base64.b64decode(data["delta"])
                        speaker_stream.write(audio_chunk)
                    elif event_type == "response.audio_transcript.done":
                        ai_transcript = data['transcript']
                        print(f"🤖 AI: {ai_transcript}")
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        user_transcript = data['transcript']
                        turn_start_timestamp = datetime.now().isoformat()
                        print(f"📝 Tú: {user_transcript}")
                    elif event_type == "response.done":
                        ai_is_speaking = False
                        print("🎤 Turno terminado. Puedes hablar ahora.\n")
                        #print("DEBUG response.done:", json.dumps(data, indent=2, ensure_ascii=False))
                        usage_data = data.get("usage")
                        if usage_data is None:
                            usage_data = data.get("item", {}).get("usage")
                        if usage_data is None:
                            usage_data = data.get("response", {}).get("usage")
                        if usage_data is None:
                            usage_data = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                        # TTFB ya fue calculado al recibir el primer audio delta
                        if not first_audio_received and ttfb_start is not None:
                            ttfb_ms = round((datetime.now() - ttfb_start).total_seconds() * 1000, 2)
                        log_turn_data(
                            datetime.now().isoformat(),
                            ttfb_ms,
                            user_transcript,
                            ai_transcript,
                            usage_data
                        )
                        turn_start_timestamp = None
                        user_transcript = None
                        ai_transcript = None
                        usage_data = None
                        ttfb_ms = None
                        ttfb_start = None
                        first_audio_received = False
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
                    data = await loop.run_in_executor(None, read_audio_blocking, mic_stream, CHUNK)
                    if ai_is_speaking:
                        continue
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
    audio_manager.terminate()

if __name__ == "__main__":
    try:
        asyncio.run(realtime_api())
    except KeyboardInterrupt:
        print("\nFin")
