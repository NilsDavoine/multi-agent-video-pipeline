"""Measure the finished video (and its scene pages), then apply every gate."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from ..config import heavy_lock
from ..contracts import QCReport, RenderOutput, Script, Word
from . import checks

# Runs inside the scene page: every element that directly holds visible text.
DOM_PROBE = """() => {
 const parse=c=>{const m=c.match(/[\\d.]+/g).map(Number);return {r:m[0],g:m[1],b:m[2],a:m.length>3?m[3]:1};};
 const lum=c=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};
   return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b);};
 const over=(top,bot)=>({r:top.r*top.a+bot.r*(1-top.a),g:top.g*top.a+bot.g*(1-top.a),
   b:top.b*top.a+bot.b*(1-top.a),a:1});
 const bgOf=el=>{const stack=[];for(let e=el;e;e=e.parentElement){
     const c=parse(getComputedStyle(e).backgroundColor);if(c.a>0)stack.push(c);if(c.a>=1)break;}
   let col={r:255,g:255,b:255,a:1};for(let i=stack.length-1;i>=0;i--)col=over(stack[i],col);return col;};
 const opac=el=>{let o=1;for(let e=el;e;e=e.parentElement)o*=+getComputedStyle(e).opacity;return o;};
 const out=[];
 for(const el of document.body.querySelectorAll("*")){
   const own=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join("").trim();
   const cs=getComputedStyle(el);
   if(!own||cs.display==="none"||cs.visibility==="hidden")continue;
   const o=opac(el); if(o<=0.05)continue;
   const r=el.getBoundingClientRect();
   if(r.width===0||r.height===0)continue; // not rendered (e.g. inside a hidden caption)
   const fg=parse(cs.color),bg=bgOf(el); const L1=lum(over(fg,bg)),L2=lum(bg);
   // hidden behind another element? probe a few points across the text box
   const pts=[[0.5,0.5],[0.15,0.5],[0.85,0.5],[0.5,0.2],[0.5,0.8]].map(([fx,fy])=>document.elementFromPoint(r.left+r.width*fx,r.top+r.height*fy));
   const occluded=pts.some(e=>e&&e!==el&&!el.contains(e)&&!e.contains(el));
   out.push({text:own,font_px:parseFloat(cs.fontSize),opacity:o,occluded,
     contrast:(Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05),
     in_frame:r.left>=0&&r.top>=0&&r.right<=innerWidth+0.5&&r.bottom<=innerHeight+0.5&&el.scrollWidth<=el.clientWidth+1});
 }
 return out;}"""


def probe_durations(video: Path) -> tuple[float, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                          "-of", "json", str(video)], capture_output=True, text=True, check=True).stdout
    d = {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}
    return d["video"], d["audio"]


def black_seconds(video: Path) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf",
                          "blackdetect=d=0.3:pix_th=0.10", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", err))


def frame_std(video: Path, t: float, w: int, h: int) -> float:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                         "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return float(np.frombuffer(raw, dtype=np.uint8)[: w * h].std())


def dom_samples(render: RenderOutput) -> list[dict]:
    """Probe every scene page mid-scene and at rest (just before the cut)."""
    from playwright.sync_api import sync_playwright

    tl = render.timeline
    samples: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": tl.width, "height": tl.height})
        for slot in tl.scenes:
            page.goto(Path(render.html[slot.scene_id]).resolve().as_uri())
            for t, at_rest in ((slot.duration * 0.5, False), (slot.duration - 0.05, True)):
                page.evaluate(f"window.__seek({t:.3f})")
                for s in page.evaluate(DOM_PROBE):
                    samples.append({**s, "scene": slot.scene_id, "t": round(t, 2), "at_rest": at_rest})
        browser.close()
    return samples


def run_qc(render: RenderOutput, script: Script, heard: list[Word] | None = None) -> tuple[QCReport, dict]:
    """Return the report and the raw measurements (kept for results.md)."""
    from ..stages.speech import transcribe

    video, tl = Path(render.video), render.timeline
    with heavy_lock():
        if heard is None:
            heard = transcribe(video)  # independent: no script hint given to the recogniser
        samples = dom_samples(render)
    video_s, audio_s = probe_durations(video)
    stds = {s.scene_id: frame_std(video, s.start + s.duration / 2, tl.width, tl.height) for s in tl.scenes}
    at_rest = {s.scene_id: sum(1 for x in samples if x["scene"] == s.scene_id and x["at_rest"])
               for s in tl.scenes}
    report = QCReport(video=str(video), checks=[
        *checks.check_transcript(tl.scenes, heard),
        *checks.check_durations(tl.scenes, video_s, audio_s),
        *checks.check_legibility(samples),
        *checks.check_nonempty(stds, at_rest, black_seconds(video)),
        checks.check_sync(tl.scenes, heard),
        checks.check_sources(script),
    ])
    return report, {"heard": [w.model_dump() for w in heard], "dom_samples": samples, "frame_std": stds}
