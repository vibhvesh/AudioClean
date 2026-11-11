import os
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter()
DATA = Path("/opt/audioclean/data/speakers")
DATA.mkdir(parents=True, exist_ok=True)
_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    token = os.getenv("HF_TOKEN")
    if not token:
        raise HTTPException(503, "Speaker detection is not configured. Install the optional speaker module and set HF_TOKEN.")
    try:
        from pyannote.audio import Pipeline
        import torch
        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=token
        )
        _pipeline.to(torch.device("cpu"))
        return _pipeline
    except Exception as exc:
        raise HTTPException(503, f"Could not load speaker model. Check Hugging Face access and installation: {exc}")

@router.post("/api/v1/speakers/detect")
async def detect_speakers(
    file: UploadFile = File(...),
    min_speakers: int = Form(1),
    max_speakers: int = Form(5)
):
    if min_speakers < 1 or max_speakers < min_speakers or max_speakers > 10:
        raise HTTPException(400, "Choose 1–10 speakers and ensure max is not below min.")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty audio file")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "Maximum upload size is 50 MB")
    job_id = uuid4().hex
    audio_path = DATA / f"{job_id}.wav"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "input"
        converted = Path(td) / "mono16k.wav"
        src.write_bytes(raw)
        import subprocess
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(converted)],
                check=True, timeout=120, capture_output=True
            )
        except FileNotFoundError:
            raise HTTPException(500, "FFmpeg is not installed")
        except subprocess.TimeoutExpired:
            raise HTTPException(408, "Audio conversion timed out")
        except subprocess.CalledProcessError:
            raise HTTPException(400, "Could not decode audio. Try WAV, MP3, M4A or OGG.")
        audio_path.write_bytes(converted.read_bytes())
    try:
        pipeline = get_pipeline()
        diarization = pipeline(
            str(audio_path),
            min_speakers=min_speakers,
            max_speakers=max_speakers
        )
        annotation = getattr(diarization, "speaker_diarization", diarization)
        segments = []
        for turn, speaker in annotation:
            segments.append({
                "speaker": str(speaker),
                "start": round(float(turn.start), 3),
                "end": round(float(turn.end), 3),
                "duration": round(float(turn.end - turn.start), 3)
            })
        speakers = sorted({s["speaker"] for s in segments})
        # Mark time ranges where two or more different speaker turns overlap.
        overlaps = []
        for i, left in enumerate(segments):
            for right in segments[i + 1:]:
                start = max(left["start"], right["start"])
                end = min(left["end"], right["end"])
                if end > start and left["speaker"] != right["speaker"]:
                    overlaps.append({
                        "start": round(start, 3), "end": round(end, 3),
                        "speakers": [left["speaker"], right["speaker"]]
                    })
        return {
            "job_id": job_id,
            "model": "pyannote/speaker-diarization-community-1",
            "speaker_count": len(speakers),
            "speakers": speakers,
            "segments": segments,
            "overlaps": overlaps,
            "audio_url": f"/files/speakers/{job_id}.wav",
            "note": "Speaker detection labels who is speaking and when. It does not yet create isolated audio tracks."
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Speaker detection failed: {exc}")
