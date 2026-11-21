"""Static HTML results report. One self-contained file, no external assets.

The mode (LIVE or REPLAY) is in the file name, the <title>, a full-width
banner at the top, the page's colour scheme and the footer, so a LIVE report
and a REPLAY report cannot be mistaken for each other.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .runner import CaseResult, Mode, RunResult

STATUS_LABEL = {
    "pass": "Pass",
    "fail": "Fail",
    "known_fail": "Known failure",
    "unexpected_pass": "Unexpected pass",
}

CSS = """
:root{--paper:#f5f2ea;--card:#fffdf8;--ink:#1b2230;--muted:#5d6475;--line:#ddd6c6;
--pass:#1d7a4a;--pass-bg:#e3f2e8;--fail:#b3261e;--fail-bg:#fbe7e4;--known:#8a5a00;--known-bg:#fbefd6;
--live:#0d6466;--live-ink:#ffffff;--replay:#9a4a00;--replay-bg:#ffd79a;--code:#f0ece2;
--mono:ui-monospace,"Cascadia Mono","Segoe UI Mono",Consolas,monospace;
--sans:"Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,"Noto Sans Arabic",sans-serif}
@media (prefers-color-scheme:dark){:root{--paper:#14171d;--card:#1c2028;--ink:#e8e4da;--muted:#a3a8b5;
--line:#323846;--pass:#6fd39b;--pass-bg:#173326;--fail:#ff8a7e;--fail-bg:#3a1d1b;--known:#f2bf5e;
--known-bg:#3a2e14;--live:#0f7c7e;--replay:#ffcf86;--replay-bg:#4a3210;--code:#252a34}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans)}
.banner{padding:14px 16px;display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline}
.banner .mode{font:800 22px/1.1 var(--sans);letter-spacing:.08em}
.banner .meta{font-size:13px;opacity:.92}
.banner.live{background:var(--live);color:var(--live-ink)}
.banner.replay{background:repeating-linear-gradient(135deg,var(--replay-bg) 0 18px,transparent 18px 36px),var(--replay-bg);
color:#3d1f00;border-bottom:3px solid var(--replay)}
@media (prefers-color-scheme:dark){.banner.replay{color:var(--replay)}}
main{max-width:980px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:26px;line-height:1.2;margin:6px 0 4px}
.lede{color:var(--muted);margin:0 0 18px;max-width:70ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:0 0 18px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:26px;line-height:1.1}
.tile span{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.tile.fail b{color:var(--fail)}.tile.pass b{color:var(--pass)}.tile.known b{color:var(--known)}
.tile.gate{border-width:2px}.tile.gate.ok{border-color:var(--pass)}.tile.gate.bad{border-color:var(--fail)}
.tile.gate b{font-size:18px;padding-top:6px}
.warn{background:var(--known-bg);border-left:4px solid var(--known);padding:10px 12px;border-radius:6px;margin:0 0 16px;font-size:14px}
.warn ul{margin:6px 0 0;padding-left:18px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}
.filters button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--card);color:var(--ink);
border-radius:999px;padding:5px 12px;cursor:pointer}
.filters button[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
ol.cases{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.case{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.case.st-fail{border-color:var(--fail);border-left-width:5px}
.case.st-known_fail,.case.st-unexpected_pass{border-left:5px solid var(--known)}
summary{list-style:none;cursor:pointer;padding:10px 12px;display:grid;grid-template-columns:auto 1fr auto;gap:4px 12px;align-items:center}
summary::-webkit-details-marker{display:none}
.pill{font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;white-space:nowrap}
.pill.pass{background:var(--pass-bg);color:var(--pass)}.pill.fail{background:var(--fail-bg);color:var(--fail)}
.pill.known_fail,.pill.unexpected_pass{background:var(--known-bg);color:var(--known)}
.cid{font:600 14px var(--mono);overflow-wrap:anywhere}
.cmeta{grid-column:2;font-size:13px;color:var(--muted)}
.dots{grid-row:1/span 2;grid-column:3;display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;max-width:320px}
.dot{font:11px var(--mono);border-radius:4px;padding:1px 5px}
.dot.ok{background:var(--pass-bg);color:var(--pass)}.dot.no{background:var(--fail-bg);color:var(--fail)}
.body{padding:0 12px 12px;display:grid;gap:10px}
.label{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin:0 0 2px}
blockquote{margin:0;padding:8px 12px;background:var(--code);border-radius:6px;font-size:15px}
.answer{margin:0;white-space:pre-wrap}
.cites{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 0;padding:0;list-style:none}
.cites li{font:12px var(--mono);border:1px solid var(--line);border-radius:4px;padding:1px 6px}
.failed{margin:0;padding:0;list-style:none;display:grid;gap:6px}
.failed li{font:13px/1.45 var(--mono);background:var(--fail-bg);color:var(--ink);border-left:4px solid var(--fail);
padding:8px 10px;border-radius:4px;overflow-wrap:anywhere}
.failed li b{color:var(--fail)}
.reason{font-size:14px;background:var(--known-bg);border-radius:6px;padding:8px 10px}
footer{max-width:980px;margin:0 auto;padding:0 16px 30px;color:var(--muted);font-size:13px}
footer .mode-tag{font-weight:800;color:var(--ink)}
.nw{white-space:nowrap}
@media (max-width:560px){summary{grid-template-columns:auto 1fr}.dots{grid-row:auto;grid-column:1/-1;justify-content:flex-start;max-width:none}
.cmeta{grid-column:1/-1}.tiles{grid-template-columns:1fr 1fr}.tile.gate{grid-column:1/-1}
h1{font-size:22px}.banner .mode{font-size:19px}}
"""

FILTER_JS = """
document.querySelectorAll('.filters button').forEach(b=>b.addEventListener('click',()=>{
document.querySelectorAll('.filters button').forEach(x=>x.setAttribute('aria-pressed',x===b));
const f=b.dataset.f;document.querySelectorAll('.case').forEach(c=>{
c.hidden=!(f==='all'||c.classList.contains('st-'+f)||(f==='fail'&&c.classList.contains('st-unexpected_pass')));});}));
"""


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def mode_banner(run: RunResult) -> str:
    a = run.agent
    who = esc(a.get("name", "unknown agent"))
    snap = a.get("knowledge_snapshot") or a.get("url") or ""
    if run.mode is Mode.LIVE:
        return (
            f'<header class="banner live" data-mode="LIVE"><div class="mode">LIVE RUN</div>'
            f'<div class="meta">The agent <b>{who}</b> answered every question just now'
            + (f" &middot; knowledge {esc(snap)}" if snap else "")
            + f' &middot; started <span class="nw">{esc(run.started_at)}</span></div></header>'
        )
    return (
        f'<header class="banner replay" data-mode="REPLAY"><div class="mode">REPLAY</div>'
        f'<div class="meta">No agent was called. Re-checked replies that <b>{who}</b> gave on '
        f'<span class="nw">{esc(run.recorded_at)}</span> against today\'s cases and procedures'
        + (f" &middot; {esc(run.transcript_path)}" if run.transcript_path else "")
        + "</div></header>"
    )


def _case_html(r: CaseResult) -> str:
    c, resp = r.case, r.response
    dots = "".join(
        f'<span class="dot {"ok" if k.passed else "no"}" title="{esc(k.message)}">{esc(k.name)}</span>'
        for k in r.checks
    )
    expected = c.expect.action + (f" &middot; {esc(c.expect.clause)} v{esc(c.expect.version)}" if c.expect.clause else "")
    meta = (f"{esc(c.project or 'no project')} &middot; {esc(c.warehouse or 'no warehouse')} &middot; "
            f"moved {esc(c.movement_date or 'no date')} &middot; {esc(c.language)}"
            f" &middot; expected {expected} &middot; got {esc(resp.action or 'no reply')}")
    cites = "".join(f"<li>{esc(x.label())}</li>" for x in resp.citations) or "<li>no citations</li>"
    failed = "".join(f"<li><b>{esc(k.name)}</b>: {esc(k.message)}</li>" for k in r.failed_checks())
    body = [
        f'<div><p class="label">Question</p><blockquote dir="auto">{esc(c.question)}</blockquote></div>',
        f'<div><p class="label">Agent reply &middot; action: {esc(resp.action or "none")}</p>'
        f'<p class="answer" dir="auto">{esc(resp.answer or resp.error or "")}</p><ul class="cites">{cites}</ul></div>',
    ]
    if failed:
        body.append(f'<div><p class="label">Failed assertions</p><ul class="failed">{failed}</ul></div>')
    if r.known_failure is not None:
        body.append(f'<div class="reason"><b>Known failure.</b> {esc(r.known_failure)}</div>')
    if r.status == "unexpected_pass":
        body.append('<div class="reason"><b>This known failure now passes.</b> Remove it from known_failures.yaml.</div>')
    is_open = " open" if r.status in ("fail", "unexpected_pass") else ""
    return (
        f'<li class="case st-{r.status}" id="{esc(c.id)}"><details{is_open}><summary>'
        f'<span class="pill {r.status}">{STATUS_LABEL[r.status]}</span>'
        f'<span class="cid">{esc(c.id)}</span><span class="dots">{dots}</span>'
        f'<span class="cmeta">{meta}</span></summary>'
        f'<div class="body">{"".join(body)}</div></details></li>'
    )


def render_report(run: RunResult) -> str:
    n = len(run.results)
    gate = run.gate_passed
    tiles = (
        f'<div class="tile"><b>{n}</b><span>cases</span></div>'
        f'<div class="tile pass"><b>{run.count("pass")}</b><span>pass</span></div>'
        f'<div class="tile fail"><b>{run.count("fail")}</b><span>new failures</span></div>'
        f'<div class="tile known"><b>{run.count("known_fail") + run.count("unexpected_pass")}</b><span>known failures</span></div>'
        f'<div class="tile gate {"ok" if gate else "bad"}"><b>{"Gate passed" if gate else "Gate failed"}</b>'
        f'<span>CI verdict</span></div>'
    )
    warn = ""
    if run.warnings:
        items = "".join(f"<li>{esc(w)}</li>" for w in run.warnings)
        warn = (f'<div class="warn"><b>{len(run.warnings)} case label(s) no longer match the procedures.</b> '
                f"The agent is still checked against the procedures; update these labels.<ul>{items}</ul></div>")
    order = {"fail": 0, "unexpected_pass": 1, "known_fail": 2, "pass": 3}
    rows = "".join(_case_html(r) for r in sorted(run.results, key=lambda r: order[r.status]))
    m = run.mode.value
    payload = json.dumps({"mode": m}).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{m} &middot; Procedure agent evals</title><meta name="eval-mode" content="{m}">
<style>{CSS}</style></head><body class="mode-{m.lower()}">
{mode_banner(run)}
<main>
<h1>Warehouse procedures assistant: {"live run" if run.mode is Mode.LIVE else "replayed run"}</h1>
<p class="lede">Each case asks the assistant a warehouse keeper's question with a project, a warehouse, the
date of the stock movement and a language, then checks the action it chose, the clause and procedure version
it cited, and that every cited clause is in force on the movement date. Answer wording is reviewed by a
person on the review sheet.</p>
<section class="tiles">{tiles}</section>
{warn}
<div class="filters" role="group" aria-label="Filter cases">
<button data-f="all" aria-pressed="true">All ({n})</button>
<button data-f="fail" aria-pressed="false">New failures ({run.count("fail") + run.count("unexpected_pass")})</button>
<button data-f="known_fail" aria-pressed="false">Known failures ({run.count("known_fail")})</button>
<button data-f="pass" aria-pressed="false">Pass ({run.count("pass")})</button>
</div>
<ol class="cases">{rows}</ol>
</main>
<footer><span class="mode-tag">{m}</span> report &middot; procedure documents {esc(run.corpus_fingerprint)} &middot;
generated {esc(run.started_at)}</footer>
<script type="application/json" id="run-meta">{payload}</script>
<script>{FILTER_JS}</script>
</body></html>
"""


def report_names(mode: Mode) -> dict[str, str]:
    m = mode.value.lower()
    return {"report": f"report-{m}.html", "results": f"results-{m}.json", "review": f"review-sheet-{m}.html"}


def write_outputs(run: RunResult, out_dir: str | Path, corpus) -> dict[str, Path]:
    from .review import render_review_sheet

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    names = report_names(run.mode)
    paths = {k: out / v for k, v in names.items()}
    paths["report"].write_text(render_report(run), encoding="utf-8")
    paths["results"].write_text(json.dumps(run.to_json(), indent=1, ensure_ascii=False), encoding="utf-8")
    paths["review"].write_text(render_review_sheet(run, corpus), encoding="utf-8")
    return paths
