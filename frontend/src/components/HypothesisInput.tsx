import React from 'react';

interface HypothesisInputProps {
  value: string;
  onChange: (v: string) => void;
  onRun: () => void;
  onLoadCache: () => void;
  isRunning: boolean;
}

const EXAMPLE_HYPOTHESES = [
  'Knocking out KRAS in HEK293 cells will reduce ERK signaling.',
  'Loss of TP53 in HCT116 cells will increase resistance to DNA damage.',
  'CRISPR knockout of MYC in HeLa cells will reduce proliferation.',
];

const CHIP_LABELS = ['KRAS / HEK293', 'TP53 / HCT116', 'MYC / HeLa'];

const HypothesisInput: React.FC<HypothesisInputProps> = ({
  value,
  onChange,
  onRun,
  onLoadCache,
  isRunning,
}) => {
  const isReady = value.trim().length > 10;

  return (
    <section style={styles.card}>
      {/* Header */}
      <div style={styles.cardHeader}>
        <span style={styles.label}>Biological Hypothesis</span>
        <h2 style={styles.title}>What do you want to test?</h2>
        <p style={styles.helperText}>
          Describe a gene knockout experiment in plain language — specify the target gene,
          cell line, and expected phenotype. AutoLab will generate a full CRISPR protocol.
        </p>
      </div>

      {/* Textarea */}
      <textarea
        style={{
          ...styles.textarea,
          opacity: isRunning ? 0.6 : 1,
        }}
        placeholder="e.g. Knocking out KRAS in HEK293 cells will reduce ERK signaling and slow proliferation."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={isRunning}
        rows={5}
      />

      {/* Example chips */}
      <div style={styles.chipsRow}>
        <span style={styles.chipsLabel}>Try an example:</span>
        <div style={styles.chips}>
          {EXAMPLE_HYPOTHESES.map((h, i) => (
            <button
              key={i}
              style={{
                ...styles.chip,
                opacity: isRunning ? 0.4 : 1,
                cursor: isRunning ? 'not-allowed' : 'pointer',
              }}
              onClick={() => onChange(h)}
              disabled={isRunning}
              title={h}
            >
              {CHIP_LABELS[i]}
            </button>
          ))}
        </div>
      </div>

      {/* Action buttons */}
      <div style={styles.actions}>
        <button
          style={{
            ...styles.btnPrimary,
            opacity: (!isReady || isRunning) ? 0.45 : 1,
            cursor: (!isReady || isRunning) ? 'not-allowed' : 'pointer',
          }}
          onClick={onRun}
          disabled={!isReady || isRunning}
        >
          {isRunning ? (
            <><span style={styles.spinner} />Running pipeline…</>
          ) : (
            <>
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none" style={{ flexShrink: 0 }}>
                <path d="M3 2.5L12 7.5L3 12.5V2.5Z" fill="currentColor" />
              </svg>
              Run Live
            </>
          )}
        </button>

        <button
          style={{
            ...styles.btnSecondary,
            opacity: isRunning ? 0.45 : 1,
            cursor: isRunning ? 'not-allowed' : 'pointer',
          }}
          onClick={onLoadCache}
          disabled={isRunning}
          title="Load a pre-computed demo result instantly"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
            <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.4" />
            <path d="M5 7L7 9L10 5.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Load Demo
        </button>
      </div>
    </section>
  );
};

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-lg)',
    boxShadow: 'var(--shadow-sm)',
    padding: '28px 28px 24px',
    display: 'flex',
    flexDirection: 'column',
    gap: 18,
  },
  cardHeader: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  label: {
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.09em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-accent)',
    marginBottom: 2,
  },
  title: {
    fontSize: 18,
    fontWeight: 700,
    color: 'var(--color-text-primary)',
    margin: 0,
  },
  helperText: {
    fontSize: 13,
    lineHeight: 1.55,
    color: 'var(--color-text-muted)',
    margin: 0,
    marginTop: 4,
    maxWidth: 620,
  },
  textarea: {
    width: '100%',
    padding: '13px 15px',
    fontSize: 14,
    lineHeight: 1.65,
    fontFamily: 'var(--font-sans)',
    color: 'var(--color-text-primary)',
    background: 'var(--color-surface-dim)',
    border: '1.5px solid var(--color-border)',
    borderRadius: 'var(--radius-md)',
    resize: 'vertical' as const,
    outline: 'none',
    transition: 'border-color 0.15s, box-shadow 0.15s',
    boxSizing: 'border-box' as const,
  },
  chipsRow: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap' as const,
    gap: 8,
  },
  chipsLabel: {
    fontSize: 12,
    color: 'var(--color-text-muted)',
    whiteSpace: 'nowrap' as const,
  },
  chips: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 6,
  },
  chip: {
    fontSize: 12,
    fontWeight: 500,
    padding: '4px 12px',
    borderRadius: 20,
    border: '1px solid var(--color-border)',
    background: 'var(--color-surface-dim)',
    color: 'var(--color-text-secondary)',
    fontFamily: 'var(--font-sans)',
    transition: 'background 0.12s, border-color 0.12s, color 0.12s',
    lineHeight: 1.5,
  },
  actions: {
    display: 'flex',
    gap: 10,
    flexWrap: 'wrap' as const,
    alignItems: 'center',
    paddingTop: 2,
  },
  btnPrimary: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 24px',
    fontSize: 14,
    fontWeight: 600,
    fontFamily: 'var(--font-sans)',
    color: '#fff',
    background: 'var(--color-accent)',
    border: 'none',
    borderRadius: 'var(--radius-md)',
    transition: 'opacity 0.15s',
    letterSpacing: '0.01em',
  },
  btnSecondary: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 500,
    fontFamily: 'var(--font-sans)',
    color: 'var(--color-text-secondary)',
    background: 'var(--color-surface)',
    border: '1.5px solid var(--color-border)',
    borderRadius: 'var(--radius-md)',
    transition: 'opacity 0.15s, background 0.12s',
    letterSpacing: '0.01em',
  },
  spinner: {
    display: 'inline-block',
    width: 13,
    height: 13,
    border: '2px solid rgba(255,255,255,0.3)',
    borderTopColor: '#fff',
    borderRadius: '50%',
    animation: 'spin 0.7s linear infinite',
    flexShrink: 0,
  },
};

export default HypothesisInput;
