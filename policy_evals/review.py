"""Human review sheet: question, answer and the cited clause text side by side.

The deterministic checks cannot tell whether an answer explains the rule
well. A reviewer reads each pair, ticks Pass or Fail, adds a note, and
exports the marks as CSV. Marks are kept in the reviewer's browser only.
"""

from __future__ import annotations

from .policies import Corpus
from .report import CSS, STATUS_LABEL, esc, mode_banner
from .runner import CaseResult, RunResult

REVIEW_CSS = """
.bar{position:sticky;top:0;z-index:2;background:var(--paper);border-bottom:1px solid var(--line);
padding:10px 0;margin:0 0 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.bar .progress{font-weight:700}
.bar button{font:inherit;font-size:14px;border:0;border-radius:8px;padding:7px 14px;background:var(--ink);color:var(--paper);cursor:pointer}
.sheet{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.rcard{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.rhead{display:flex;gap:8px 12px;flex-wrap:wrap;align-items:center;margin:0 0 8px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.col{min-width:0}
.clause{border-left:3px solid var(--line);padding:2px 0 2px 10px;margin:0 0 8px}
.clause h4{margin:0;font:600 13px var(--mono)}
.clause p{margin:2px 0 0;font-size:14px}
.clause.missing{border-color:var(--fail)}.clause.missing h4{color:var(--fail)}
.verdict{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-top:10px;padding-top:10px;border-top:1px dashed var(--line)}
.verdict label{display:flex;gap:6px;align-items:center;font-weight:600}
.verdict textarea{flex:1 1 220px;min-height:38px;font:inherit;font-size:14px;border:1px solid var(--line);
border-radius:6px;padding:6px 8px;background:var(--paper);color:var(--ink)}
@media (max-width:640px){.cols{grid-template-columns:1fr}}
"""

REVIEW_JS = """
const KEY='review:'+document.querySelector('meta[name=eval-mode]').content+':'+document.body.dataset.run;
let marks={};try{marks=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){marks={}}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(marks))}catch(e){}};
const cards=[...document.querySelectorAll('.rcard')];
function progress(){const n=cards.filter(c=>marks[c.id]&&marks[c.id].v).length;
document.querySelector('.progress').textContent=n+' of '+cards.length+' reviewed';}
cards.forEach(c=>{const m=marks[c.id]||{};
c.querySelectorAll('input[type=radio]').forEach(r=>{if(r.value===m.v)r.checked=true;
r.addEventListener('change',()=>{marks[c.id]={...(marks[c.id]||{}),v:r.value};save();progress();});});
const t=c.querySelector('textarea');t.value=m.n||'';
t.addEventListener('input',()=>{marks[c.id]={...(marks[c.id]||{}),n:t.value};save();});});
progress();
document.getElementById('export').addEventListener('click',()=>{
const q=s=>'"'+String(s||'').replace(/"/g,'""')+'"';
const rows=[['case','checks','reviewer_verdict','note']].concat(cards.map(c=>[c.id,c.dataset.status,(marks[c.id]||{}).v,(marks[c.id]||{}).n]));
const blob=new Blob([rows.map(r=>r.map(q).join(',')).join('\\n')],{type:'text/csv'});
const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='review-'+KEY.replace(/[^a-z0-9]+/gi,'-')+'.csv';a.click();});
"""


def _clauses_html(r: CaseResult, corpus: Corpus) -> str:
    if not r.response.citations:
        return '<p class="clause"><span class="label">No clause cited.</span></p>'
    out = []
    for cit in r.response.citations:
        v = corpus.get(cit.document, cit.version)
        clause = v.clauses.get(cit.clause) if v else None
        if clause is None:
            out.append(f'<div class="clause missing"><h4>{esc(cit.label())}</h4>'
                       f"<p>Not found in the procedure documents.</p></div>")
        else:
            out.append(f'<div class="clause"><h4>{esc(cit.label())} &middot; {esc(clause.title)}</h4>'
                       f"<p>{esc(clause.text)}</p></div>")
    return "".join(out)


def render_review_sheet(run: RunResult, corpus: Corpus) -> str:
    cards = []
    for i, r in enumerate(run.results):
        c, resp = r.case, r.response
        name = f"v{i}"
        cards.append(f"""<li class="rcard" id="{esc(c.id)}" data-status="{r.status}">
<div class="rhead"><span class="pill {r.status}">Checks: {STATUS_LABEL[r.status]}</span>
<span class="cid">{esc(c.id)}</span><span class="cmeta">{esc(c.project or 'no project')} &middot; {esc(c.warehouse or 'no warehouse')} &middot; moved {esc(c.movement_date or 'no date')} &middot; {esc(c.language)}</span></div>
<div class="cols"><div class="col"><p class="label">Question</p><blockquote dir="auto">{esc(c.question)}</blockquote>
<p class="label" style="margin-top:8px">Answer &middot; action: {esc(resp.action or 'none')}</p>
<p class="answer" dir="auto">{esc(resp.answer or resp.error or '')}</p></div>
<div class="col"><p class="label">Cited clause text (from the version cited)</p>{_clauses_html(r, corpus)}</div></div>
<div class="verdict"><span class="label">Explanation</span>
<label><input type="radio" name="{name}" value="pass"> Pass</label>
<label><input type="radio" name="{name}" value="fail"> Fail</label>
<textarea aria-label="Reviewer note for {esc(c.id)}" placeholder="Note (optional)"></textarea></div></li>""")
    m = run.mode.value
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{m} &middot; Review sheet &middot; Procedure agent evals</title><meta name="eval-mode" content="{m}">
<style>{CSS}{REVIEW_CSS}</style></head><body data-run="{esc(run.recorded_at)}">
{mode_banner(run)}
<main>
<h1>Review sheet: is each answer a fair reading of the clause?</h1>
<p class="lede">Read the answer next to the clause text it cites and judge the explanation only. Version, clause
and action were already checked automatically (see the badge on each card). Marks stay in this browser; use
Export CSV to hand them in.</p>
<div class="bar"><span class="progress">0 reviewed</span><button id="export" type="button">Export CSV</button></div>
<ol class="sheet">{"".join(cards)}</ol>
</main>
<footer><span class="mode-tag">{m}</span> review sheet &middot; replies recorded {esc(run.recorded_at)}</footer>
<script>{REVIEW_JS}</script>
</body></html>
"""
