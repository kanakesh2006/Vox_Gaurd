import os
import io
import json
import asyncio
import numpy as np
import parselmouth
import librosa
import aiohttp
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Voice-Auth & Anti-Spoofing")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
active_alerts = []
alert_queues = []

# Prompts
NORMAL_TASK_PROMPT = """You are a helpful AI banking assistant. You assist users with transferring money, checking balances, and other banking tasks. Keep your answers concise, helpful, and natural."""

COVERT_PROTOCOL_PROMPT = """You are a helpful AI banking assistant, but there is a system delay. You MUST stall the user using ordinary banking dialogue. 
DO NOT mention fraud, security, duress, or verification failure.
If the amount is large or you just need to stall, use phrases like:
- "That's a slightly larger transfer, so I need to re-verify a couple of details before confirming — give me about thirty seconds."
- "Hmm, I'm not seeing the OTP come through yet on my end. Let me resend it — one moment please."
- "There's a temporary system delay on this transaction. It's saved as pending, and our team will call you back shortly to complete it."
Keep it natural.
"""

SOFT_REJECT_PROMPT = """I'm sorry, I am having trouble verifying your audio. Please try again later."""

# Mock liveness check
def liveness_check(audio_chunk: bytes) -> bool:
    # In a real app, use AASIST or RawNet2. We assume true for MVP.
    return True

def estimate_speaking_rate(y, sr):
    # Simple heuristic for speaking rate
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    peaks = librosa.util.peak_pick(onset_env, pre_max=3, post_max=3, pre_avg=3, post_avg=5, delta=0.5, wait=10)
    duration = librosa.get_duration(y=y, sr=sr)
    if duration == 0: return 0
    return len(peaks) / duration

def extract_features(audio_chunk: bytes, sr: int = 16000) -> dict:
    try:
        # We assume 16-bit PCM audio from the frontend
        y = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        
        if len(y) < sr * 0.5: # Need at least 0.5 seconds
            return {}

        snd = parselmouth.Sound(y, sampling_frequency=sr)
        pitch = snd.to_pitch()
        point_process = parselmouth.praat.call(snd, "To PointProcess (periodic, cc)", 75, 500)
        
        try:
            jitter = parselmouth.praat.call(point_process, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
        except:
            jitter = 0.0
            
        try:
            shimmer = parselmouth.praat.call([snd, point_process], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6)
        except:
            shimmer = 0.0

        f0_values = pitch.selected_array["frequency"]
        f0_values = f0_values[f0_values > 0]
        
        return {
            "pitch_mean": float(np.mean(f0_values)) if len(f0_values) else 0.0,
            "pitch_std": float(np.std(f0_values)) if len(f0_values) else 0.0,
            "jitter": jitter,
            "shimmer": shimmer,
            "rms_energy": float(np.mean(librosa.feature.rms(y=y))),
            "speaking_rate": estimate_speaking_rate(y, sr),
        }
    except Exception as e:
        logger.error(f"Error extracting features: {e}")
        return {}

def compute_duress_score(features: dict, baseline: dict) -> float:
    if not features or not baseline: return 0.0
    
    def z(key):
        val = features.get(key, 0.0)
        base_val = baseline.get(key, 0.0)
        std = baseline.get(f"{key}_std", 1.0)
        if std == 0.0: std = 1.0
        return abs(val - base_val) / std

    weights = {"pitch_mean": 0.3, "jitter": 0.3, "shimmer": 0.2, "speaking_rate": 0.2}
    score = sum(weights[k] * z(k) for k in weights if k in features and k in baseline)
    return score

async def saaras_stt(audio_chunk: bytes) -> str:
    # Saaras STT API
    url = "https://api.sarvam.ai/speech-to-text"
    headers = {"api-subscription-key": settings.SARVAM_API_KEY}
    
    # Save audio_chunk to a temporary file in memory as wav
    # Assuming audio_chunk is raw PCM 16kHz, we need to wrap it in WAV
    import soundfile as sf
    y = np.frombuffer(audio_chunk, dtype=np.int16)
    
    # If the chunk is empty or very small, just return empty string
    if len(y) == 0:
        return ""
        
    buf = io.BytesIO()
    sf.write(buf, y, 16000, format='WAV', subtype='PCM_16')
    buf.seek(0)
    
    data = aiohttp.FormData()
    data.add_field('file', buf, filename='audio.wav', content_type='audio/wav')
    data.add_field('model', 'saaras:v3')
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    return res_json.get("transcript", "")
                else:
                    logger.error(f"Saaras API Error: {resp.status} {await resp.text()}")
                    return ""
        except Exception as e:
            logger.error(f"STT Error: {e}")
            return ""

async def sarvam_105b_chat(messages: list, system_prompt: str) -> str:
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": settings.SARVAM_API_KEY
    }
    
    payload_messages = [{"role": "system", "content": system_prompt}] + messages
    
    payload = {
        "model": "sarvam-105b",
        "messages": payload_messages
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    return res_json["choices"][0]["message"]["content"]
                else:
                    logger.error(f"Sarvam-105B API Error: {resp.status} {await resp.text()}")
                    return "Sorry, I am facing some issues."
        except Exception as e:
            logger.error(f"Chat Error: {e}")
            return "Sorry, I am facing some issues."

async def bulbul_tts(text: str) -> str:
    # Returns base64 string
    url = "https://api.sarvam.ai/text-to-speech"
    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": settings.SARVAM_API_KEY
    }
    
    payload = {
        "text": text,
        "language_code": "hi-IN",
        "speaker": "shubh",
        "model": "bulbul:v3"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    return res_json.get("audios", [""])[0]
                else:
                    logger.error(f"Bulbul API Error: {resp.status} {await resp.text()}")
                    return ""
        except Exception as e:
            logger.error(f"TTS Error: {e}")
            return ""

def fire_silent_alert(session_data: dict):
    alert = {
        "session_id": session_data.get("id"),
        "risk_score": session_data.get("risk_score", 0),
        "transcript": [m["content"] for m in session_data.get("history", []) if m["role"] == "user"],
        "stage": session_data.get("stage"),
        "amount": session_data.get("amount")
    }
    active_alerts.append(alert)
    
    # Notify all listening dashboards
    for q in alert_queues:
        q.put_nowait(alert)

async def acoustic_branch(audio_chunk: bytes, session: dict) -> dict:
    features = extract_features(audio_chunk)
    if not features:
        return {"is_live": True, "is_duress": False, "risk_score": 0.0}

    if session["stage"] == "greeting" and "baseline" not in session:
        session["baseline"] = features
        return {"is_live": True, "is_duress": False, "risk_score": 0.0}

    baseline = session.get("baseline", features)
    risk_score = compute_duress_score(features, baseline)
    is_live = liveness_check(audio_chunk)

    return {
        "is_live": is_live,
        "is_duress": risk_score > settings.DURESS_THRESHOLD,
        "risk_score": risk_score,
    }

async def process_chunk(audio_bytes: bytes, session: dict):
    transcript_task = asyncio.create_task(saaras_stt(audio_bytes))
    acoustic_task = asyncio.create_task(acoustic_branch(audio_bytes, session))
    
    transcript, signal = await asyncio.gather(transcript_task, acoustic_task)
    return transcript, signal

def extract_amount(text: str) -> float:
    # simple heuristic for amount
    import re
    matches = re.findall(r'\d+', text.replace(',', ''))
    if matches:
        return float(matches[0])
    return None

def route(transcript: str, signal: dict, amount: float, session: dict) -> str:
    high_value = amount is not None and amount > settings.AMOUNT_THRESHOLD

    if not signal["is_live"]:
        session["stage"] = "soft_reject"
        return SOFT_REJECT_PROMPT

    if signal["is_duress"] or (high_value and signal["risk_score"] > settings.STEPUP_THRESHOLD):
        session["stage"] = "covert_protocol"
        session["risk_score"] = signal["risk_score"]
        fire_silent_alert(session)
        return COVERT_PROTOCOL_PROMPT

    session["stage"] = "task_execution"
    return NORMAL_TASK_PROMPT

@app.websocket("/call")
async def voice_loop(ws: WebSocket):
    await ws.accept()
    session_id = id(ws)
    session_state = {"id": session_id, "stage": "greeting", "history": [], "amount": None}
    
    audio_buffer = bytearray()
    silence_frames = 0
    
    try:
        while True:
            # We wait for the client to send audio
            audio_chunk = await ws.receive_bytes()
            
            # Simple VAD (Voice Activity Detection) on the backend
            y = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.mean(librosa.feature.rms(y=y)))
            
            if rms > 0.005:
                audio_buffer.extend(audio_chunk)
                silence_frames = 0
            else:
                if len(audio_buffer) > 0:
                    silence_frames += 1
            
            # If we've seen ~1.5s of silence (assuming ~256ms per chunk, 6 frames)
            if silence_frames >= 6 and len(audio_buffer) > 16000 * 2: # At least 1 sec of audio
                logger.info(f"Processing turn, buffer size: {len(audio_buffer)} bytes")
                
                audio_bytes = bytes(audio_buffer)
                audio_buffer.clear()
                silence_frames = 0
                
                transcript, signal = await process_chunk(audio_bytes, session_state)
                
                if not transcript.strip():
                    continue # Skip if empty transcription
                    
                logger.info(f"Transcript: {transcript} | Signal: {signal}")
                
                session_state["history"].append({"role": "user", "content": transcript})
                
                amt = extract_amount(transcript)
                if amt is not None:
                    session_state["amount"] = amt
                    
                system_prompt = route(transcript, signal, session_state["amount"], session_state)
                
                reply = await sarvam_105b_chat(
                    messages=session_state["history"],
                    system_prompt=system_prompt,
                )
                session_state["history"].append({"role": "assistant", "content": reply})
                
                tts_base64 = await bulbul_tts(reply)
                
                # Send TTS base64 to client and the transcript for UI display
                await ws.send_json({
                    "type": "response",
                    "audio": tts_base64,
                    "transcript": transcript,
                    "reply": reply,
                    "risk_score": signal["risk_score"]
                })
            
    except WebSocketDisconnect:
        logger.info(f"Client disconnected {session_id}")
    except Exception as e:
        logger.error(f"WS error: {e}")

@app.get("/alerts/stream")
async def alerts_stream():
    q = asyncio.Queue()
    alert_queues.append(q)
    
    async def event_generator():
        try:
            while True:
                alert = await q.get()
                yield f"data: {json.dumps(alert)}\n\n"
        except asyncio.CancelledError:
            alert_queues.remove(q)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/")
def index():
    if os.path.exists("frontend/dist/index.html"):
        return HTMLResponse(open("frontend/dist/index.html", encoding="utf-8").read())
    return HTMLResponse("<h1>Frontend not built yet. Run npm run build in frontend directory.</h1>")

app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

@app.get("/{full_path:path}")
def catch_all(full_path: str):
    if os.path.exists("frontend/dist/index.html"):
        return HTMLResponse(open("frontend/dist/index.html", encoding="utf-8").read())
    return HTMLResponse("<h1>Frontend not built yet. Run npm run build in frontend directory.</h1>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
