"""
Protocol Export Utility

Converts a pipeline result dict (frontend response shape) into a
print-ready HTML document styled as a formal lab protocol.

Usage:
    from utils.protocol_exporter import export_protocol
    html = export_protocol(result_dict)
    # Return as HTTP response or write to file.

The generated HTML includes print-optimised CSS so the user can
File → Print → Save as PDF directly from any browser.
"""

from __future__ import annotations

import html as _html
from datetime import date


# ── Public entry point ─────────────────────────────────────────────────────

def export_protocol(result: dict) -> str:
    """
    Convert a pipeline result dict to a standalone, printable HTML document.

    Args:
        result: The JSON-serialisable dict returned by the AutoLab pipeline
                (_to_response shape from server.py).

    Returns:
        Complete HTML string (utf-8, self-contained — no external assets).
    """
    gene  = _e(result.get("gene", "UNKNOWN"))
    today = date.today().strftime("%B %d, %Y")

    sections = "\n".join([
        _section_hypothesis(result),
        _section_experimental_design(result),
        _section_sgrna(result),
        _section_feasibility(result),
        _section_protocol_steps(result),
        _section_validation(result),
        _section_execution_timeline(result),
        _section_reviewer_notes(result),
        _section_confidence(result),
        _section_literature(result),
    ])

    return _HTML_TEMPLATE.format(
        gene=gene,
        today=today,
        hypothesis_text=_e(result.get("hypothesis_text", "")),
        sections=sections,
    )


# ── Section builders ───────────────────────────────────────────────────────

def _section_hypothesis(r: dict) -> str:
    text = _e(r.get("hypothesis_text", ""))
    return _section("Hypothesis", f'<blockquote class="hypothesis">{text}</blockquote>')


def _section_experimental_design(r: dict) -> str:
    rows = [
        ("Target Gene",    r.get("gene", "")),
        ("Cell Line",      r.get("cell_line", "")),
        ("Edit Type",      r.get("edit_type", "")),
        ("Phenotype",      r.get("phenotype", "")),
        ("System Context", r.get("system_context", "")),
        ("Transfection",   r.get("transfection_method", "")),
    ]
    table = _kv_table(rows)

    assumptions = r.get("assumptions", [])
    assumption_html = ""
    if assumptions:
        items = "".join(f"<li>{_e(a)}</li>" for a in assumptions)
        assumption_html = f'<p class="sub-label">Assumptions made by the parser:</p><ul>{items}</ul>'

    return _section("Experimental Design", table + assumption_html)


def _section_sgrna(r: dict) -> str:
    candidates = r.get("sgrna_candidates", [])
    if not candidates:
        return _section("sgRNA Selection", "<p class='empty'>No sgRNA candidates available.</p>")

    rows_html = ""
    for i, g in enumerate(candidates):
        gc_pct = round(g.get("efficiency_score", 0) * 100)
        rows_html += (
            f"<tr>"
            f"<td>#{i + 1}</td>"
            f"<td class='mono'>{_e(g.get('guide_id', ''))}</td>"
            f"<td class='mono seq'>{_e(g.get('sequence', ''))}</td>"
            f"<td>{gc_pct}%</td>"
            f"<td class='mono'>{_e(g.get('pam', 'NGG'))}</td>"
            f"</tr>"
        )

    table = (
        "<table>"
        "<thead><tr><th>Rank</th><th>Guide ID</th><th>Sequence (5′→3′)</th><th>GC %</th><th>PAM</th></tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
    )
    note = "<p class='note'>GC content used as efficiency proxy. Optimal range: 40–70%.</p>"
    return _section("sgRNA Selection", table + note)


def _section_feasibility(r: dict) -> str:
    verdict = r.get("feasibility_verdict", "pass")
    verdict_labels = {"pass": "Feasible", "warn": "Proceed with Caution", "block": "Blocked"}
    verdict_label  = verdict_labels.get(verdict, verdict.title())
    verdict_class  = {"pass": "pass", "warn": "warn", "block": "block"}.get(verdict, "warn")

    body = f'<p class="verdict {verdict_class}">{verdict_label}</p>'

    flags = r.get("feasibility_flags", [])
    if flags:
        for f in flags:
            sev   = _e(f.get("severity", "warning"))
            msg   = _e(f.get("message", ""))
            body += f'<div class="flag {sev}"><strong>[{sev.upper()}]</strong> {msg}</div>'
    else:
        body += "<p>No feasibility concerns flagged.</p>"

    return _section("Feasibility Assessment", body)


def _section_protocol_steps(r: dict) -> str:
    steps = r.get("protocol_steps", [])
    if not steps:
        return _section("Protocol Steps", "<p class='empty'>No protocol steps available.</p>")

    items = ""
    for step in steps:
        num      = step.get("step_number", "")
        title    = _e(step.get("title", ""))
        dur_h    = step.get("duration_hours")
        dur_str  = ""
        if dur_h is not None:
            if dur_h >= 24:
                days = dur_h / 24
                dur_str = f"{days:.1f}d" if days % 1 else f"{int(days)}d"
            else:
                dur_str = f"{dur_h}h"
        duration_badge = f' <span class="duration">{dur_str}</span>' if dur_str else ""
        items += f"<li><strong>Step {num}: {title}</strong>{duration_badge}</li>"

    total = r.get("total_duration_days", 0)
    footer = f'<p class="note">Estimated total duration: <strong>{total} days</strong></p>'
    return _section("Protocol Steps", f"<ol>{items}</ol>{footer}")


def _section_validation(r: dict) -> str:
    assay  = _e(r.get("validation_assay", "Not specified"))
    method = _e(r.get("transfection_method", "Not specified"))
    rows   = [("Validation Assay", assay), ("Delivery Method", method)]
    return _section("Validation Plan", _kv_table(rows))


def _section_execution_timeline(r: dict) -> str:
    timeline = r.get("timeline", [])
    reagents = r.get("reagents", [])

    if not timeline and not reagents:
        return _section("Execution Timeline", "<p class='empty'>No timeline data available.</p>")

    body = ""
    if timeline:
        rows = "".join(
            f"<tr><td class='day-col'>Day {e.get('day', '')}</td><td>{_e(e.get('activity', ''))}</td></tr>"
            for e in timeline
        )
        body += (
            "<p class='sub-label'>Day-by-Day Activities</p>"
            "<table><thead><tr><th>Day</th><th>Activity</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    if reagents:
        rows = "".join(
            f"<tr><td>{_e(re.get('item', ''))}</td><td>{_e(re.get('purpose', ''))}</td></tr>"
            for re in reagents
        )
        body += (
            "<p class='sub-label' style='margin-top:16px'>Reagent Checklist</p>"
            "<table><thead><tr><th>Reagent / Item</th><th>Purpose</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    return _section("Execution Timeline", body)


def _section_reviewer_notes(r: dict) -> str:
    summary = _e(r.get("review_summary", ""))
    verdict = _e(r.get("verdict", ""))
    flags   = r.get("flags", [])
    patches = r.get("patches_applied", [])

    body = ""
    if verdict:
        verdict_display = verdict.replace("_", " ").title()
        verdict_class   = "pass" if "approv" in verdict else ("block" if "major" in verdict else "warn")
        body += f'<p class="verdict {verdict_class}">Scientific Verdict: {verdict_display}</p>'

    if summary:
        body += f"<p>{summary}</p>"

    for f in flags:
        sev  = _e(f.get("severity", "info"))
        cat  = _e(f.get("category", ""))
        iss  = _e(f.get("issue", ""))
        rec  = _e(f.get("recommendation", ""))
        cls  = "block" if sev == "critical" else ("warn" if sev == "warning" else "info-flag")
        body += (
            f'<div class="flag {cls}">'
            f'<strong>[{sev.upper()}] {cat}</strong><br>'
            f'{iss}'
            f'{"<br><em>→ " + rec + "</em>" if rec else ""}'
            f"</div>"
        )

    if patches:
        items = "".join(f"<li>{_e(p)}</li>" for p in patches)
        body += f'<p class="sub-label">Auto-patches applied:</p><ul>{items}</ul>'

    if not body:
        body = "<p>No reviewer notes available.</p>"

    return _section("Reviewer Notes", body)


def _section_confidence(r: dict) -> str:
    score  = r.get("confidence_score")
    if score is None:
        return ""

    label   = _e(r.get("confidence_label", ""))
    factors = r.get("confidence_factors", [])
    cls     = "pass" if score > 75 else ("warn" if score >= 50 else "block")

    body = f'<p class="verdict {cls}">Confidence Score: {score}% — {label}</p>'

    if score < 50:
        body += (
            '<div class="flag block">'
            'Low confidence experiment. Consider adjusting gene, model system, or phenotype.'
            "</div>"
        )

    if factors:
        rows = "".join(
            f"<tr>"
            f"<td>{_e(f.get('label', ''))}</td>"
            f"<td>{'−' + str(f.get('penalty', 0)) if f.get('triggered') else '✓'}</td>"
            f"</tr>"
            for f in factors
        )
        body += (
            "<table><thead><tr><th>Factor</th><th>Impact</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    return _section("Experiment Confidence", body)


def _section_literature(r: dict) -> str:
    sources = r.get("literature_sources", [])
    if not sources:
        return ""

    items = ""
    for s in sources:
        title   = _e(s.get("title", ""))
        authors = _e(s.get("authors", ""))
        journal = _e(s.get("journal", ""))
        year    = _e(str(s.get("year", "")))
        finding = _e(s.get("key_finding", ""))
        url     = s.get("pubmed_url", "")
        link    = f' <a href="{_e(url)}">[PubMed]</a>' if url else ""
        items += (
            f"<li>"
            f"<strong>{title}</strong>{link}<br>"
            f"<em>{authors}</em> · {journal} ({year})"
            f'{"<br>" + finding if finding else ""}'
            f"</li>"
        )

    return _section("Supporting Literature", f"<ul class='literature'>{items}</ul>")


# ── Shared helpers ─────────────────────────────────────────────────────────

def _e(text: str) -> str:
    """HTML-escape a string."""
    return _html.escape(str(text))


def _section(title: str, body: str) -> str:
    return f'<section><h2>{_e(title)}</h2>{body}</section>'


def _kv_table(rows: list[tuple[str, str]]) -> str:
    trs = "".join(
        f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>"
        for k, v in rows
        if v
    )
    return f"<table class='kv'><tbody>{trs}</tbody></table>"


# ── HTML shell ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoLab Protocol — {gene}</title>
<style>
/* ── Reset ──────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* ── Base ──────────────────────────── */
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
  font-size: 13px;
  line-height: 1.65;
  color: #1a1a2e;
  background: #fff;
  padding: 48px 56px;
  max-width: 860px;
  margin: 0 auto;
}}

/* ── Header ────────────────────────── */
header {{
  border-bottom: 2px solid #1a1a2e;
  padding-bottom: 16px;
  margin-bottom: 32px;
}}
header .brand {{
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #666;
  margin-bottom: 6px;
}}
header h1 {{
  font-size: 22px;
  font-weight: 800;
  color: #1a1a2e;
  margin-bottom: 4px;
}}
header .meta {{
  font-size: 12px;
  color: #555;
}}

/* ── Sections ──────────────────────── */
section {{
  margin-bottom: 30px;
  page-break-inside: avoid;
}}
section:last-child {{ margin-bottom: 0; }}

h2 {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #444;
  border-bottom: 1px solid #ddd;
  padding-bottom: 5px;
  margin-bottom: 12px;
}}

/* ── Hypothesis ────────────────────── */
blockquote.hypothesis {{
  font-size: 14px;
  font-weight: 500;
  border-left: 3px solid #1a1a2e;
  padding-left: 14px;
  color: #1a1a2e;
  font-style: italic;
}}

/* ── Tables ────────────────────────── */
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  margin-bottom: 8px;
}}
th, td {{
  padding: 6px 10px;
  text-align: left;
  border: 1px solid #ddd;
  vertical-align: top;
}}
thead th {{
  background: #f4f4f6;
  font-weight: 700;
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}}
table.kv th {{
  background: #f4f4f6;
  width: 180px;
  font-weight: 600;
  font-size: 12px;
}}
tr:nth-child(even) td {{ background: #fafafa; }}

/* ── Lists ─────────────────────────── */
ul, ol {{
  padding-left: 20px;
  margin-bottom: 8px;
}}
li {{ margin-bottom: 5px; }}
ul.literature {{ list-style: none; padding-left: 0; }}
ul.literature li {{
  border-left: 3px solid #ddd;
  padding-left: 12px;
  margin-bottom: 12px;
}}

/* ── Verdicts / Flags ──────────────── */
.verdict {{
  display: inline-block;
  font-weight: 700;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  margin-bottom: 10px;
}}
.verdict.pass  {{ background: #dcfce7; color: #166534; border: 1px solid #86efac; }}
.verdict.warn  {{ background: #fef9c3; color: #854d0e; border: 1px solid #fcd34d; }}
.verdict.block {{ background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }}

.flag {{
  padding: 8px 12px;
  border-radius: 4px;
  margin-bottom: 8px;
  font-size: 12.5px;
  line-height: 1.55;
}}
.flag.warning  {{ background: #fef9c3; border-left: 4px solid #fcd34d; }}
.flag.blocker,
.flag.block    {{ background: #fee2e2; border-left: 4px solid #fca5a5; }}
.flag.info-flag {{ background: #eff6ff; border-left: 4px solid #93c5fd; }}

/* ── Misc ──────────────────────────── */
.mono  {{ font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px; }}
.seq   {{ letter-spacing: 0.04em; }}
.day-col {{ white-space: nowrap; width: 70px; font-weight: 600; }}
.duration {{ font-size: 11px; font-weight: 600; color: #555;
             background: #f0f0f0; padding: 1px 7px; border-radius: 20px;
             margin-left: 8px; }}
.note {{ font-size: 11.5px; color: #666; margin-top: 6px; font-style: italic; }}
.sub-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
              text-transform: uppercase; color: #666; margin: 10px 0 6px; }}
.empty {{ color: #999; font-style: italic; }}

/* ── Footer ────────────────────────── */
footer {{
  margin-top: 40px;
  padding-top: 12px;
  border-top: 1px solid #ddd;
  font-size: 11px;
  color: #888;
  display: flex;
  justify-content: space-between;
}}

/* ── Print ─────────────────────────── */
@media print {{
  body {{ padding: 0; }}
  section {{ page-break-inside: avoid; }}
  header {{ page-break-after: avoid; }}
  a {{ color: inherit; text-decoration: none; }}
  footer {{ position: fixed; bottom: 0; left: 0; right: 0;
            background: #fff; padding: 8px 56px; }}
}}
</style>
</head>
<body>

<header>
  <p class="brand">AutoLab · AI-Assisted CRISPR Design</p>
  <h1>CRISPR Protocol — {gene}</h1>
  <p class="meta">Generated: {today} &nbsp;·&nbsp; Hypothesis: <em>{hypothesis_text}</em></p>
</header>

{sections}

<footer>
  <span>AutoLab — AI-Assisted CRISPR Protocol</span>
  <span>{gene} · {today}</span>
</footer>

</body>
</html>
"""
