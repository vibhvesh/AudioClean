from pathlib import Path
from uuid import uuid4
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt, stft, istft
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from speaker_detection import router as speaker_router

BASE = Path(__file__).resolve().parent
DATA = Path("/opt/audioclean/data")
ORIGINALS = DATA / "original"
CLEANED = DATA / "cleaned"
for folder in (ORIGINALS, CLEANED):
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Canberra AudioClean", version="0.1.0")
app.mount("/files", StaticFiles(directory=str(DATA)), name="files")
app.include_router(speaker_router)

PAGE = """<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canberra AudioClean</title>
<style>
body{font:16px system-ui;background:#101820;color:#edf2f4;max-width:850px;margin:35px auto;padding:0 18px}
.panel{background:#1c2a35;padding:22px;border-radius:14px;margin:18px 0}
h1{margin-bottom:4px}small{color:#aab7c4}button{background:#f28c28;border:0;padding:12px 18px;border-radius:8px;font-weight:700;cursor:pointer}
input,select{padding:10px;margin:8px 0;max-width:100%}audio{width:100%;margin:10px 0}
label{display:block;margin-top:10px}#status{white-space:pre-wrap;color:#ffd08a}
</style></head><body>
<h1>Canberra AudioClean</h1><small>CPU audio cleanup • API + review console • v0.1</small>
<div class="panel"><h3>Clean an audio recording</h3>
<p>Upload an audio file. The first release applies speech-band filtering and a light spectral gate.</p>
<form id="f"><input type="file" id="audio" accept="audio/*" required>
<label>Noise type / annotation</label><select id="tag"><option>General background noise</option><option>Static / hiss</option><option>Wind / rumble</option><option>Clicks / spikes</option><option>Traffic / engine</option><option>Distortion / clipping</option><option>Overlapping voices</option><option>Important speech - preserve</option></select>
<br><button>Enhance audio</button></form><p id="status"></p></div>
<div class="panel"><h3>Speaker detection</h3>
<p>Find who speaks when, including overlapping speech. This labels speaker turns; it does not yet split voices into separate audio files.</p>
<form id="speakerForm"><input type="file" id="speakerAudio" accept="audio/*" required>
<label>Minimum speakers</label><select id="minSpeakers"><option>1</option><option>2</option><option>3</option></select>
<label>Maximum speakers</label><select id="maxSpeakers"><option>2</option><option selected>3</option><option>4</option><option>5</option><option>6</option></select>
<br><button>Detect speakers</button></form><p id="speakerStatus"></p><div id="speakerResults"></div></div>
<div class="panel" id="results" hidden><h3>Original</h3><audio id="before" controls></audio><h3>Enhanced</h3><audio id="after" controls></audio><p id="report"></p></div>
<script>
const f=document.getElementById('f'),status=document.getElementById('status');
f.addEventListener('submit',async e=>{e.preventDefault();const file=document.getElementById('audio').files[0];if(!file)return;
status.textContent='Processing…';const data=new FormData();data.append('file',file);data.append('tag',document.getElementById('tag').value);
try{const r=await fetch('/api/v1/enhance',{method:'POST',body:data});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Processing failed');
document.getElementById('before').src=j.original_url;document.getElementById('after').src=j.enhanced_url;
document.getElementById('report').textContent='Job '+j.job_id+' • '+j.sample_rate+' Hz • '+j.duration_seconds+' seconds • '+j.method;
document.getElementById('results').hidden=false;status.textContent='Complete';}catch(err){status.textContent='Error: '+err.message;}});
document.getElementById('speakerForm').addEventListener('submit',async e=>{
e.preventDefault();const status=document.getElementById('speakerStatus'),out=document.getElementById('speakerResults');
const file=document.getElementById('speakerAudio').files[0];if(!file)return;
const min=document.getElementById('minSpeakers').value,max=document.getElementById('maxSpeakers').value;
if(Number(max)<Number(min)){status.textContent='Maximum speakers must be at least the minimum.';return;}
const data=new FormData();data.append('file',file);data.append('min_speakers',min);data.append('max_speakers',max);
status.textContent='Analysing audio… first run may take longer while the model loads.';out.innerHTML='';
try{const r=await fetch('/api/v1/speakers/detect',{method:'POST',body:data});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Detection failed');
status.textContent='Found '+j.speaker_count+' speaker(s). '+j.overlaps.length+' overlapping intervals.';
let html='<audio controls src="'+j.audio_url+'"></audio><h4>Speaker timeline</h4>';
for(const s of j.speakers){const seg=j.segments.filter(x=>x.speaker===s);html+='<div style="border-top:1px solid #40515f;padding:10px 0"><b>'+s+'</b> — '+seg.length+' turns';for(const t of seg){html+='<div>'+t.start.toFixed(2)+'s – '+t.end.toFixed(2)+'s</div>';}html+='</div>';}
if(j.overlaps.length){html+='<h4>Overlapping speech</h4>';for(const o of j.overlaps){html+='<div>'+o.start.toFixed(2)+'s – '+o.end.toFixed(2)+'s: '+o.speakers.join(' + ')+'</div>';}}
html+='<p><small>'+j.note+'</small></p>';out.innerHTML=html;
}catch(err){status.textContent='Error: '+err.message;}
});
</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE

@app.get("/health")
def health():
    return {"status": "ok", "service": "Canberra AudioClean", "version": "0.1.0"}

def spectral_gate(x: np.ndarray, rate: int) -> np.ndarray:
    # Conservative spectral gate using the first 0.35 s as a noise estimate.
    if len(x) < int(rate * 0.5):
        return x
    nperseg = min(1024, max(256, 2 ** int(np.floor(np.log2(max(256, rate * 0.032))))))
    noverlap = nperseg * 3 // 4
    _, _, z = stft(x, fs=rate, nperseg=nperseg, noverlap=noverlap, boundary="zeros")
    noise_frames = max(1, min(z.shape[1], int(0.35 * rate / (nperseg - noverlap))))
    noise = np.median(np.abs(z[:, :noise_frames]), axis=1, keepdims=True)
    magnitude = np.abs(z)
    # Soft mask avoids hard musical-noise artifacts.
    threshold = noise * 1.8
    mask = np.clip((magnitude - threshold) / (magnitude + 1e-10), 0.12, 1.0)
    _, y = istft(z * mask, fs=rate, nperseg=nperseg, noverlap=noverlap, input_onesided=True, boundary=True)
    return y[:len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x)-len(y)))

@app.post("/api/v1/enhance")
async def enhance(file: UploadFile = File(...), tag: str = Form("General background noise")):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty audio file")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "Maximum upload size is 50 MB")
    job = uuid4().hex
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "input"
        wav = Path(td) / "input.wav"
        src.write_bytes(raw)
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", str(wav)],
                           check=True, timeout=60, capture_output=True)
        except FileNotFoundError:
            raise HTTPException(500, "FFmpeg is not installed")
        except subprocess.CalledProcessError:
            raise HTTPException(400, "Could not decode audio. Try WAV, MP3, M4A or OGG.")
        rate, data = wavfile.read(wav)
    x = data.astype(np.float32)
    if data.dtype.kind in "iu":
        x /= max(abs(np.iinfo(data.dtype).min), np.iinfo(data.dtype).max)
    x = np.nan_to_num(x)
    if len(x) < 100:
        raise HTTPException(400, "Audio is too short")
    # Speech-focused band-pass for radio / voice recordings.
    sos = butter(4, [180, 3800], btype="bandpass", fs=rate, output="sos")
    filtered = sosfiltfilt(sos, x)
    cleaned = spectral_gate(filtered, rate)
    peak = float(np.max(np.abs(cleaned)))
    if peak > 0.98:
        cleaned *= 0.98 / peak
    original_path = ORIGINALS / f"{job}.wav"
    clean_path = CLEANED / f"{job}.wav"
    wavfile.write(original_path, rate, x.astype(np.float32))
    wavfile.write(clean_path, rate, cleaned.astype(np.float32))
    return {"job_id": job, "tag": tag, "sample_rate": rate,
            "duration_seconds": round(len(x) / rate, 2),
            "method": "speech band-pass + conservative spectral gate (CPU DSP)",
            "original_url": f"/files/original/{job}.wav",
            "enhanced_url": f"/files/cleaned/{job}.wav"}

@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    original = ORIGINALS / f"{job_id}.wav"
    cleaned = CLEANED / f"{job_id}.wav"
    if not original.exists() or not cleaned.exists():
        raise HTTPException(404, "Job not found")
    return {"job_id": job_id, "original_url": f"/files/original/{job_id}.wav",
            "enhanced_url": f"/files/cleaned/{job_id}.wav"}
