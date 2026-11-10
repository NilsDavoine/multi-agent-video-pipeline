"""Scene pages: a fixed HTML/CSS template filled with an agent's SceneDesign.

Agents never write HTML: they choose a layout and words, the template does the rest.
Each page exposes window.__seek(t) which sets every animated element for time t,
so rendering is deterministic (one screenshot per frame, no wall clock).
"""
from __future__ import annotations

import html
import json

from ..contracts import Cue, SceneDesign, Word

ACCENTS = {"blue": "#1f5fbf", "green": "#1d7a46", "orange": "#b4540a", "red": "#b3261e"}

# The example document shown in "invoice" scenes. Invented names and figures.
INVOICE = {
    "number": [("Invoice no.", "INV-0148")],
    "parties": [("Date", "3 March"), ("From", "Pinecone Print"), ("To", "Mia Laurent")],
    "items": [("200 flyers", "€80.00")],
    "vat": [("VAT 17 %", "€13.60"), ("Total", "€93.60")],
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:%(w)dpx;height:%(h)dpx;overflow:hidden;background:#f5f2ea;
 font-family:"DejaVu Sans","Liberation Sans",Arial,sans-serif;color:#1b1b1f}
.blob{position:absolute;border-radius:50%%;background:%(accent)s;opacity:.08}
.bar{position:absolute;left:0;top:0;height:5px;background:%(accent)s}
h1{position:absolute;left:28px;top:22px;font-size:26px;line-height:1.15;max-width:300px;color:#1b1b1f}
.chips{position:absolute;left:28px;top:118px;display:flex;flex-direction:column;gap:8px;align-items:flex-start}
.chip{font-size:18px;font-weight:bold;color:#fff;background:%(accent)s;padding:4px 10px;border-radius:4px}
.bubble{position:absolute;left:28px;top:96px;width:330px;min-height:84px;background:#fff;border-radius:14px;
 padding:12px 16px;box-shadow:0 2px 8px rgba(0,0,0,.12);font-size:20px;line-height:1.3}
.bubble:after{content:"";position:absolute;left:24px;bottom:-12px;border:12px solid transparent;
 border-top-color:#fff;border-bottom:0}
.who{font-size:16px;font-weight:bold;color:%(accent)s;margin-bottom:4px}
.paid{position:absolute;width:118px;height:150px;background:#fff;border:2px solid #c9c4b8;border-radius:6px;
 top:92px;padding:10px;font-size:16px}
.stamp{margin-top:56px;font-weight:bold;font-size:20px;color:#b3261e;border:3px solid #b3261e;
 text-align:center;transform:rotate(-12deg)}
.card{position:absolute;right:26px;top:18px;width:262px;background:#fff;border:2px solid #c9c4b8;
 border-radius:8px;padding:10px 12px;font-size:16px}
.card .t{font-weight:bold;font-size:18px;margin-bottom:4px}
.row{display:flex;justify-content:space-between;padding:2px 6px;line-height:1.25;border-radius:4px;border:2px solid transparent}
.row.on{background:#fff6d6;border-color:%(accent)s}
.sep{height:1px;background:#d8d3c8;margin:3px 0}
.title{position:absolute;left:0;right:0;top:92px;text-align:center;font-size:34px;font-weight:bold;color:#1b1b1f}
.title + .chips{left:0;right:0;top:160px;align-items:center}
.cap{position:absolute;left:50%%;bottom:16px;transform:translateX(-50%%);max-width:600px;
 background:rgba(17,17,20,.92);color:#fff;font-size:20px;line-height:1.25;padding:5px 12px;border-radius:6px;
 text-align:center;white-space:nowrap}
.cap b{color:#ffd84d}
"""

JS = """
const D=%(data)s;
const ease=x=>1-Math.pow(1-Math.min(Math.max(x,0),1),3);
function anim(el,t){
  const t0=+el.dataset.t0, k=ease((t-t0)/0.3), kind=el.dataset.anim;
  if(kind==="pop"){el.style.opacity=k;el.style.transform=`scale(${0.6+0.4*k})`;}
  else if(kind==="up"){el.style.opacity=k;el.style.transform=`translateY(${(1-k)*14}px)`;}
  else if(kind==="left"){el.style.opacity=k;el.style.transform=`translateX(${(1-k)*40}px)`;}
}
window.__seek=function(t){
  document.querySelectorAll("[data-anim]").forEach(el=>anim(el,t));
  document.querySelector(".bar").style.width=(100*Math.min(t/D.duration,1))+"%%";
  document.querySelectorAll(".blob").forEach((b,i)=>{
    b.style.transform=`translate(${Math.sin(t*0.9+i)*18}px,${Math.cos(t*0.7+i*2)*12}px)`;});
  document.querySelectorAll(".word").forEach(w=>{w.style.visibility=t>=+w.dataset.t0?"visible":"hidden";});
  const cap=document.querySelector(".cap"); const c=D.cues.find(c=>t>=c.start&&t<c.end);
  if(!c){cap.style.display="none";return;}
  cap.style.display="block";
  cap.innerHTML=c.words.map(w=>t>=w.start&&t<w.end+0.08?`<b>${w.html}</b>`:w.html).join(" ");
};
window.__seek(0);
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def build_scene(design: SceneDesign, words: list[Word], cues: list[Cue], duration: float,
                lead_name: str, lead_words: int, width: int, height: int) -> str:
    """Return the page for one scene. Times are scene-relative seconds."""
    accent = ACCENTS[design.accent]
    css = CSS % {"w": width, "h": height, "accent": accent}
    body: list[str] = ['<div class="blob" style="width:220px;height:220px;left:-60px;bottom:-90px"></div>',
                       '<div class="blob" style="width:160px;height:160px;right:180px;top:-70px"></div>',
                       '<div class="bar"></div>']

    def spoken_at(phrase: str) -> float:
        toks = phrase.lower().split()
        for i in range(len(words)):
            got = [w.text.lower().strip(".,:;!?") for w in words[i:i + len(toks)]]
            if got == [t.strip(".,:;!?") for t in toks]:
                return words[i].start
        return 0.4

    chips = "".join(f'<div class="chip" data-anim="pop" data-t0="{spoken_at(k):.3f}">{_esc(k)}</div>'
                    for k in design.keywords)
    if design.layout == "bubble":
        typed = " ".join(f'<span class="word" data-t0="{w.start:.3f}">{_esc(w.text)}</span>'
                         for w in words[:lead_words])
        body.append(f'<h1 data-anim="up" data-t0="0.05">{_esc(design.heading)}</h1>')
        body.append(f'<div class="bubble" data-anim="pop" data-t0="0.1"><div class="who">{_esc(lead_name)}</div>'
                    f'{typed}</div>')
        for i, x in enumerate((392, 506)):
            body.append(f'<div class="paid" style="left:{x}px" data-anim="left" data-t0="{0.3 + i * 0.6:.2f}">'
                        f'INV-0148<div class="stamp">PAID</div></div>')
    elif design.layout == "invoice":
        body.append(f'<h1 data-anim="up" data-t0="0.05">{_esc(design.heading)}</h1>')
        body.append(f'<div class="chips">{chips}</div>')
        rows = []
        for group, items in INVOICE.items():
            on = " on" if group == design.highlight else ""
            t0 = 0.5 if on else 0.1
            for label, value in items:
                rows.append(f'<div class="row{on}" data-anim="up" data-t0="{t0}"><span>{_esc(label)}</span>'
                            f'<span>{_esc(value)}</span></div>')
            rows.append('<div class="sep"></div>')
        body.append(f'<div class="card" data-anim="left" data-t0="0"><div class="t">INVOICE</div>{"".join(rows[:-1])}</div>')
    else:  # title
        body.append(f'<div class="title" data-anim="pop" data-t0="0.1">{_esc(design.heading)}</div>')
        body.append(f'<div class="chips">{chips}</div>')
    body.append('<div class="cap"></div>')

    # Cues are consecutive chunks of the scene's words: slice them back in order.
    cue_data, i = [], 0
    for c in cues:
        n = len(c.text.split())
        cue_data.append({"start": c.start, "end": c.end, "words": [
            {"html": _esc(w.text), "start": w.start, "end": w.end} for w in words[i:i + n]]})
        i += n
    data = {"duration": duration, "cues": cue_data}
    js = JS % {"data": json.dumps(data)}
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body>{"".join(body)}<script>{js}</script></body></html>')
