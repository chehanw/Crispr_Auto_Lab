import { useState } from 'react';
import Header from './components/Header';
import HypothesisInput from './components/HypothesisInput';
import PipelineProgress from './components/PipelineProgress';
import type { PipelineStage } from './components/PipelineProgress';
import ResultsPanel from './components/ResultsPanel';
import type { PipelineResult } from './components/ResultsPanel';

// ── Mock result (mirrors real backend output schema) ───────────────────────

const MOCK_RESULT: PipelineResult = {
  // ── Hypothesis ───────────────────────────────────────────────────────────
  hypothesis_text:
    'Knocking out TP53 in HeLa cells will impair apoptosis and drive resistance to cisplatin treatment.',

  // ── Parsed experiment design ─────────────────────────────────────────────
  gene: 'TP53',
  cell_line: 'HeLa',
  edit_type: 'Knockout',
  phenotype: 'Impaired apoptosis and increased resistance to cisplatin treatment',
  system_context: 'Cancer cell survival · Chemotherapy response',
  transfection_method: 'Lipofectamine 3000',
  assumptions: [
    'Cell line defaulted to HeLa based on experimental context',
    'Edit type inferred as knockout from "knocking out" phrasing',
  ],

  // ── Feasibility ──────────────────────────────────────────────────────────
  feasibility_verdict: 'warn',
  feasibility_flags: [
    {
      severity: 'warning',
      message:
        'HeLa cells carry HPV-18 E6, which constitutively degrades p53 — the knockout phenotype may be attenuated or absent.',
    },
    {
      severity: 'warning',
      message:
        'Cisplatin resistance assays require baseline IC50 determination; allow 3 extra days for dose–response curve.',
    },
  ],

  // ── sgRNAs ───────────────────────────────────────────────────────────────
  sgrna_candidates: [
    { guide_id: 'TP53_19453_CCATTGTTCAATATCGTCCG', sequence: 'CCATTGTTCAATATCGTCCG', efficiency_score: 0.45, pam: 'NGG' },
    { guide_id: 'TP53_19455_GATCCACTCACAGTTTCCAT', sequence: 'GATCCACTCACAGTTTCCAT', efficiency_score: 0.45, pam: 'NGG' },
    { guide_id: 'TP53_19454_GAGCGCTGCTCAGATAGCGA', sequence: 'GAGCGCTGCTCAGATAGCGA', efficiency_score: 0.60, pam: 'NGG' },
  ],

  // ── Scientific review ────────────────────────────────────────────────────
  verdict: 'approve_with_warnings',
  flags: [
    {
      severity: 'critical',
      category: 'controls',
      issue: 'No non-targeting sgRNA control specified.',
      recommendation: 'Include a validated non-targeting sgRNA carried through the full pipeline.',
      patchable: true,
    },
    {
      severity: 'warning',
      category: 'validation',
      issue: 'HeLa cells carry HPV-18 E6, which constitutively degrades p53.',
      recommendation: 'Use a p53-WT cell line (A549, MCF7) or include a WT control for comparison.',
      patchable: true,
    },
    {
      severity: 'warning',
      category: 'guide_selection',
      issue: 'Only one sgRNA tested — recommend validating with ≥2 independent guides.',
      recommendation: 'Test at least two independent sgRNAs targeting different exons.',
      patchable: true,
    },
  ],
  review_summary:
    'The protocol is well-structured with appropriate molecular validation steps. ' +
    'The key scientific caveat is that HeLa cells already lack functional p53 due to HPV-18 E6; ' +
    'a non-targeting control and second guide are strongly recommended. ' +
    'Local patches have been applied automatically.',
  patches_applied: [
    'guide_selection: added backup_guides [TP53_19453, TP53_19455] for independent validation',
    'validation: added off_target_validation_recommended=true',
    'statistics: added statistical_plan_note (n=3, α=0.05, t-test/ANOVA)',
  ],
  protocol_steps: [
    { step_number: 1, title: 'Cell Culture Preparation',     duration_hours: 24   },
    { step_number: 2, title: 'sgRNA / Cas9 Construct Prep',  duration_hours: 3    },
    { step_number: 3, title: 'Lipofectamine Transfection',   duration_hours: 48   },
    { step_number: 4, title: 'Puromycin Selection',          duration_hours: 168  },
    { step_number: 5, title: 'Clonal Isolation',             duration_hours: 336  },
    { step_number: 6, title: 'T7E1 + Sanger Sequencing',     duration_hours: 8    },
    { step_number: 7, title: 'Western Blot (anti-p53)',       duration_hours: 8    },
    { step_number: 8, title: 'Annexin V / Cisplatin Assay',  duration_hours: 72   },
  ],
  total_duration_days: 25,
  validation_assay: 'T7E1, Sanger sequencing, Western blot, Annexin V/PI',
  literature_sources: [
    {
      title: 'TP53 mutation and loss in human cancers: implications for therapy',
      journal: 'Nature Reviews Cancer',
      year: '2021',
    },
    {
      title: 'Optimized sgRNA design to maximize activity and minimize off-target effects',
      journal: 'Nature Biotechnology',
      year: '2016',
    },
  ],
  reagents: [
    { item: 'pX459 Cas9-sgRNA plasmid',      purpose: 'All-in-one expression vector' },
    { item: 'TP53 sgRNA (GAGCGCTGCTCAGATAGCGA)', purpose: 'Target sequence for Cas9 editing' },
    { item: 'Non-targeting control sgRNA',   purpose: 'Negative control for off-target effects' },
    { item: 'Lipofectamine 3000',             purpose: 'Transfection reagent' },
    { item: 'Puromycin (2 µg/mL)',           purpose: 'Selection antibiotic' },
    { item: 'Anti-p53 antibody (DO-1)',       purpose: 'Western blot knockout confirmation' },
    { item: 'Cisplatin (0.1–50 µM)',         purpose: 'Functional phenotype assay' },
    { item: 'Annexin V-FITC / PI kit',       purpose: 'Apoptosis flow cytometry' },
  ],
  timeline: [
    { day: 1,  activity: 'Seed HeLa cells; verify >95% viability' },
    { day: 2,  activity: 'Prepare Cas9-sgRNA plasmid; form Lipofectamine complexes' },
    { day: 3,  activity: 'Transfect; incubate 48h' },
    { day: 5,  activity: 'Begin puromycin selection (2 µg/mL)' },
    { day: 8,  activity: 'Remove selection; allow recovery' },
    { day: 9,  activity: 'Single-cell cloning at limiting dilution' },
    { day: 23, activity: 'Extract genomic DNA; T7E1 assay' },
    { day: 24, activity: 'Sanger sequencing + Western blot' },
    { day: 25, activity: 'Cisplatin IC50 assay + Annexin V flow cytometry' },
  ],
};

// ── Pipeline stages ────────────────────────────────────────────────────────

const INITIAL_STAGES: PipelineStage[] = [
  { id: 'parse',       label: 'Parse Hypothesis',       status: 'idle' },
  { id: 'feasibility', label: 'Feasibility Check',      status: 'idle' },
  { id: 'sgrna',       label: 'sgRNA Retrieval',        status: 'idle', detail: 'Brunello library · 77,441 guides' },
  { id: 'literature',  label: 'Literature Grounding',   status: 'idle', detail: 'PubMed fetch + analysis' },
  { id: 'protocol',    label: 'Protocol Generation',    status: 'idle', detail: 'Claude Sonnet' },
  { id: 'review',      label: 'Review + Patch',         status: 'idle', detail: 'Claude Haiku' },
  { id: 'execution',   label: 'Execution Packet',       status: 'idle', detail: 'Claude Haiku' },
];

// ── App ────────────────────────────────────────────────────────────────────

export default function App() {
  const [hypothesis, setHypothesis] = useState('');
  const [stages, setStages]         = useState<PipelineStage[]>(INITIAL_STAGES);
  const [result, setResult]         = useState<PipelineResult | null>(null);
  const [isRunning, setIsRunning]   = useState(false);

  // Simulate pipeline progression through stages (mock — no real backend yet)
  const simulatePipeline = (fromCache: boolean) => {
    setIsRunning(true);
    setResult(null);

    const delays = fromCache
      ? [0, 0, 0, 0, 0, 0, 0]        // cache: all instant
      : [400, 800, 300, 1200, 2500, 1800, 1200]; // live: realistic timing

    const stageStatus: StageStatus = fromCache ? 'skipped' : 'done';
    const ids = INITIAL_STAGES.map((s) => s.id);

    // Reset stages
    setStages(INITIAL_STAGES.map((s) => ({ ...s, status: 'idle' })));

    let elapsed = 0;
    ids.forEach((id, i) => {
      const activateAt = elapsed;
      const doneAt     = elapsed + (fromCache ? 0 : delays[i]);
      elapsed          = doneAt + 50;

      // Mark active
      setTimeout(() => {
        setStages((prev) =>
          prev.map((s) => s.id === id ? { ...s, status: fromCache ? 'skipped' : 'active' } : s)
        );
      }, activateAt);

      // Mark done
      setTimeout(() => {
        setStages((prev) =>
          prev.map((s) => s.id === id ? { ...s, status: stageStatus } : s)
        );

        // Show result after last stage
        if (i === ids.length - 1) {
          setTimeout(() => {
            setResult(MOCK_RESULT);
            setIsRunning(false);
          }, 200);
        }
      }, doneAt + (fromCache ? 10 : delays[i]));
    });
  };

  type StageStatus = 'idle' | 'active' | 'done' | 'skipped' | 'error';

  return (
    <div style={styles.root}>
      <Header />

      <main style={styles.main}>
        <div style={styles.container}>

          {/* Input card */}
          <HypothesisInput
            value={hypothesis}
            onChange={setHypothesis}
            onRun={() => simulatePipeline(false)}
            onLoadCache={() => simulatePipeline(true)}
            isRunning={isRunning}
          />

          {/* Pipeline progress (shown once pipeline starts) */}
          <PipelineProgress stages={stages} />

          {/* Results */}
          <ResultsPanel result={result} />

        </div>
      </main>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
  },
  main: {
    flex: 1,
    padding: '32px 32px 64px',
  },
  container: {
    maxWidth: 1100,
    margin: '0 auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
};
