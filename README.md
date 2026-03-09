# CRISPR AutoLab

An autonomous CRISPR experimental design assistant powered by Claude. Input a free-text biological hypothesis — get a complete, peer-reviewed knockout protocol in minutes.

---

## What It Does

AutoLab runs an 8-stage pipeline that takes a plain-English hypothesis like:

> *"I want to knock out TP53 in HeLa cells to study its role in apoptosis"*

...and produces a complete experimental package including sgRNA candidates, a step-by-step protocol, a scientific review with flags, an execution timeline, reagent checklist, literature citations, and an experiment confidence score — all exportable as a print-ready HTML document.

---

## Pipeline

```
Input hypothesis
     │
     ▼
[1] Parse Hypothesis          Claude Haiku   → structured gene/cell/edit-type JSON
[2] Feasibility Check         Claude Haiku   → compatibility flags, essentiality warnings
[3] sgRNA Retrieval           (no LLM)       → top-3 guides from Brunello library (77,441 guides)
[4] Literature Evidence       Claude Haiku   → PubMed-grounded methods & validation strategies
[5] Confidence Score          (no LLM)       → 0–100 score from 5 weighted factors
[6] Protocol Generation       Claude Sonnet  → full step-by-step CRISPR protocol
[7] Review + Patch            Claude Haiku   → peer review, rule-based auto-fixes
[8] Execution Packet          Claude Haiku   → reagent checklist, day-by-day timeline
     │
     ▼
Results dashboard  +  HTML export
```

All stages stream in real time to the frontend via Server-Sent Events.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · Uvicorn |
| LLM | Anthropic Claude (Sonnet 4.6 + Haiku 4.5) |
| sgRNA data | Brunello genome-wide library |
| Literature | NCBI PubMed E-utilities |
| Frontend | React 19 · TypeScript · Vite |
| Validation | Pydantic v2 |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Anthropic API key
- NCBI API key (optional — increases PubMed rate limits)

### 1. Clone & install backend

```bash
git clone https://github.com/chehanw/Crispr_Auto_Lab.git
cd Crispr_Auto_Lab
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your keys
```

```env
ANTHROPIC_API_KEY=sk-ant-...
PUBMED_API_KEY=...          # optional
```

### 3. Start the backend

```bash
python server.py
# API available at http://localhost:8000
```

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
```

### 5. Try it

Open `http://localhost:5173`, type a hypothesis, and click **Run**. Or click **Load Demo** to instantly load a cached TP53 result without spending API credits.

---

## Project Structure

```
Crispr_Auto_Lab/
├── server.py                   # FastAPI server (endpoints + pipeline orchestration)
├── config.py                   # API keys, model selection, paths
├── requirements.txt
├── agents/
│   ├── parser.py               # Stage 1 — parse hypothesis to structured JSON
│   ├── feasibility_check.py    # Stage 2 — compatibility + essentiality checks
│   ├── sgrna_retriever.py      # Stage 3 — Brunello library lookup
│   ├── literature_analyst.py   # Stage 4 — PubMed-grounded guidance extraction
│   ├── confidence_scorer.py    # Stage 5 — deterministic 0–100 scoring model
│   ├── protocol_generator.py   # Stage 6 — full protocol generation
│   ├── reviewer.py             # Stage 7 — peer review
│   ├── protocol_patcher.py     # Stage 7.5 — rule-based auto-fixes (no LLM)
│   └── execution_planner.py    # Stage 8 — reagent list + day-by-day timeline
├── models/
│   └── schemas.py              # Pydantic models for all pipeline stages
├── utils/
│   ├── llm_utils.py            # JSON extraction, retry logic
│   ├── pubmed_fetcher.py       # NCBI E-utilities integration
│   ├── sgrna_lookup.py         # Brunello library parser + in-memory index
│   └── protocol_exporter.py    # HTML document generation
├── data/
│   └── sgrna_library.csv       # Pre-processed sgRNA candidates
├── output/                     # Cached pipeline results (timestamped JSON)
├── tests/                      # pytest test suite
└── frontend/                   # React + TypeScript UI
    └── src/
        ├── App.tsx
        ├── api/pipeline.ts
        └── components/
            ├── HypothesisInput.tsx
            ├── PipelineProgress.tsx
            └── ResultsPanel.tsx
```

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/run/stream` | Stream pipeline as SSE — emits stage events then final result |
| `GET` | `/demo/{gene}` | Load most recent cached result for a gene (e.g. `/demo/tp53`) |
| `POST` | `/export` | Generate printable HTML protocol document (file download) |
| `GET` | `/health` | Health check |

### Request format

```json
POST /run/stream
{ "hypothesis": "Knock out BRCA1 in MCF-7 cells to study DNA damage response" }
```

### SSE stream format

```
data: {"type": "stage", "id": "parse", "status": "done"}
data: {"type": "stage", "id": "sgrna", "status": "active"}
...
data: {"type": "result", "data": { ... full pipeline output ... }}
```

---

## Confidence Score

Each experiment gets a 0–100 confidence score computed from five factors — no LLM calls, deterministic:

| Factor | Penalty |
|---|---|
| Gene is DepMap common essential (lethality confound) | −30 |
| Primary or hard-to-transfect cell line | −15 |
| Best sgRNA efficiency < 60% GC-content | −10 |
| Fewer than 2 literature sources found | −10 |
| Any feasibility flag present | −10 |

**High** > 75 · **Moderate** 50–75 · **Low** < 50

---

## Feasibility Checks

The feasibility stage runs two layers before spending tokens on protocol generation:

1. **Instant lookup** — hardcoded table of known biological incompatibilities (e.g. TP53 knockout in TP53-null HeLa cells, essential gene knockouts in non-permissive lines)
2. **LLM review** — Claude Haiku for combinations not covered by the lookup table

Blockers halt the pipeline. Warnings proceed but are surfaced prominently in the results.

---

## Protocol Export

The **Export Protocol** button in the results panel POSTs the current result to `/export` and downloads a self-contained HTML file styled for print-to-PDF. The document includes all protocol steps, reagent checklist, sgRNA sequences, reviewer flags, and literature citations.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `PUBMED_API_KEY` | No | NCBI API key (increases rate limits) |

---

## Running Tests

```bash
pytest tests/
```
