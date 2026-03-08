import { useRef, useState } from 'react';
import Header from './components/Header';
import HypothesisInput from './components/HypothesisInput';
import PipelineProgress from './components/PipelineProgress';
import type { PipelineStage } from './components/PipelineProgress';
import ResultsPanel from './components/ResultsPanel';
import type { PipelineResult } from './components/ResultsPanel';
import { runLiveStream, loadDemo } from './api/pipeline';

// ── Pipeline stage definitions ─────────────────────────────────────────────

const INITIAL_STAGES: PipelineStage[] = [
  { id: 'parse',       label: 'Parse Hypothesis',     status: 'idle' },
  { id: 'feasibility', label: 'Feasibility Check',    status: 'idle' },
  { id: 'sgrna',       label: 'sgRNA Retrieval',      status: 'idle', detail: 'Brunello library · 77,441 guides' },
  { id: 'literature',  label: 'Literature Grounding', status: 'idle', detail: 'PubMed fetch + analysis' },
  { id: 'protocol',    label: 'Protocol Generation',  status: 'idle', detail: 'Claude Sonnet' },
  { id: 'review',      label: 'Review + Patch',       status: 'idle', detail: 'Claude Haiku' },
  { id: 'execution',   label: 'Execution Packet',     status: 'idle', detail: 'Claude Haiku' },
];

const resetStages = (): PipelineStage[] =>
  INITIAL_STAGES.map((s) => ({ ...s, status: 'idle' as const }));

const setStageStatus = (
  prev: PipelineStage[],
  id: string,
  status: PipelineStage['status'],
): PipelineStage[] => prev.map((s) => (s.id === id ? { ...s, status } : s));

// ── App ────────────────────────────────────────────────────────────────────

export default function App() {
  const [hypothesis, setHypothesis] = useState('');
  const [stages, setStages]         = useState<PipelineStage[]>(INITIAL_STAGES);
  const [result, setResult]         = useState<PipelineResult | null>(null);
  const [isRunning, setIsRunning]   = useState(false);
  const [error, setError]           = useState<string | null>(null);

  const abortRef  = useRef<AbortController | null>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const genRef    = useRef(0);

  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  };

  const cancelCurrent = () => {
    abortRef.current?.abort();
    clearTimers();
  };

  // ── Run Live — stages driven by real SSE events from the backend ──────────

  const handleRunLive = async () => {
    cancelCurrent();
    const gen = ++genRef.current;
    const controller = new AbortController();
    abortRef.current = controller;

    setIsRunning(true);
    setError(null);
    setResult(null);
    setStages(resetStages());

    try {
      await runLiveStream(
        hypothesis,
        {
          onStage: (id, status) => {
            if (genRef.current !== gen) return;
            setStages((prev) => setStageStatus(prev, id, status));
          },
          onResult: (data) => {
            if (genRef.current !== gen) return;
            setResult(data);
            setIsRunning(false);
          },
          onError: (message) => {
            if (genRef.current !== gen) return;
            setError(message);
            setStages(resetStages());
            setIsRunning(false);
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (genRef.current !== gen) return;
      if ((err as Error).name === 'AbortError') return;
      setError((err as Error).message ?? 'Something went wrong.');
      setStages(resetStages());
      setIsRunning(false);
    }
  };

  // ── Load Demo — instant cascade through cached result ─────────────────────

  const handleLoadDemo = async () => {
    cancelCurrent();
    const gen = ++genRef.current;
    const controller = new AbortController();
    abortRef.current = controller;

    setIsRunning(true);
    setError(null);
    setResult(null);
    setStages(resetStages());

    let data: PipelineResult;
    try {
      data = await loadDemo('tp53', controller.signal);
    } catch (err) {
      if (genRef.current !== gen) return;
      if ((err as Error).name === 'AbortError') return;
      setError((err as Error).message ?? 'Failed to load demo.');
      setStages(resetStages());
      setIsRunning(false);
      return;
    }

    if (genRef.current !== gen) return;

    // Flash stages as "skipped" in a quick cascade, then show result
    let delay = 0;
    INITIAL_STAGES.forEach(({ id }) => {
      const t = setTimeout(() => {
        if (genRef.current !== gen) return;
        setStages((prev) => setStageStatus(prev, id, 'skipped'));
      }, delay);
      timersRef.current.push(t);
      delay += 80;
    });

    const t = setTimeout(() => {
      if (genRef.current !== gen) return;
      setResult(data);
      setIsRunning(false);
    }, delay + 150);
    timersRef.current.push(t);
  };

  return (
    <div style={styles.root}>
      <Header />

      <main style={styles.main}>
        <div style={styles.container}>

          <HypothesisInput
            value={hypothesis}
            onChange={setHypothesis}
            onRun={handleRunLive}
            onLoadCache={handleLoadDemo}
            isRunning={isRunning}
          />

          {error && (
            <div style={styles.errorBanner}>
              <span style={styles.errorIcon}>✗</span>
              <span style={styles.errorText}>{error}</span>
              <button
                style={styles.errorDismiss}
                onClick={() => setError(null)}
                aria-label="Dismiss error"
              >
                ×
              </button>
            </div>
          )}

          <PipelineProgress stages={stages} />

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
    padding: '24px 28px 56px',
  },
  container: {
    maxWidth: 1100,
    margin: '0 auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  errorBanner: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 10,
    padding: '12px 16px',
    background: 'var(--color-critical-bg)',
    border: '1px solid #fca5a5',
    borderRadius: 'var(--radius-md)',
    color: 'var(--color-critical)',
  },
  errorIcon: {
    fontWeight: 700,
    fontSize: 14,
    flexShrink: 0,
    marginTop: 1,
  },
  errorText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 1.5,
    color: 'var(--color-text-primary)',
  },
  errorDismiss: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    fontSize: 18,
    lineHeight: 1,
    color: 'var(--color-text-muted)',
    padding: '0 2px',
    flexShrink: 0,
  },
};
