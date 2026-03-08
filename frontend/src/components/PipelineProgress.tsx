import React from 'react';

export type StageStatus = 'idle' | 'active' | 'done' | 'error' | 'skipped';

export interface PipelineStage {
  id: string;
  label: string;
  detail?: string;
  status: StageStatus;
}

interface PipelineProgressProps {
  stages: PipelineStage[];
}

const DOT_COLOR: Record<StageStatus, string> = {
  idle:    'var(--color-border)',
  active:  'var(--color-accent)',
  done:    'var(--color-success)',
  error:   'var(--color-critical)',
  skipped: 'var(--color-text-muted)',
};

const DOT_BG: Record<StageStatus, string> = {
  idle:    'var(--color-surface-dim)',
  active:  'var(--color-accent-subtle)',
  done:    'var(--color-success-bg)',
  error:   'var(--color-critical-bg)',
  skipped: 'var(--color-surface-dim)',
};

function DotIcon({ status }: { status: StageStatus }) {
  const color  = DOT_COLOR[status];
  const bg     = DOT_BG[status];
  const active = status === 'active';
  const done   = status === 'done';
  const error  = status === 'error';

  return (
    <div
      style={{
        width: 24,
        height: 24,
        borderRadius: '50%',
        background: bg,
        border: `2px solid ${color}`,
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        animation: active ? 'pulse 1.4s ease-in-out infinite' : 'none',
        transition: 'border-color 0.2s, background 0.2s',
      }}
    >
      {done && (
        <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
          <path d="M2 5.5L4.5 8L9 3" stroke="var(--color-success)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {error && (
        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-critical)', lineHeight: 1 }}>✗</span>
      )}
      {active && (
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--color-accent)' }} />
      )}
      {status === 'skipped' && (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path d="M2 5h6M6 3l2 2-2 2" stroke="var(--color-text-muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </div>
  );
}

const PipelineProgress: React.FC<PipelineProgressProps> = ({ stages }) => {
  const anyActive = stages.some((s) => s.status !== 'idle');
  if (!anyActive) return null;

  const doneCount = stages.filter((s) => s.status === 'done' || s.status === 'skipped').length;
  const total     = stages.length;

  return (
    <section style={styles.card}>
      <div style={styles.header}>
        <span style={styles.label}>Pipeline</span>
        <span style={styles.counter}>{doneCount} / {total} stages</span>
      </div>

      <div style={styles.stages}>
        {stages.map((stage, i) => {
          const isActive = stage.status === 'active';
          return (
            <div key={stage.id} style={styles.row}>
              {/* Track column */}
              <div style={styles.track}>
                <DotIcon status={stage.status} />
                {i < stages.length - 1 && (
                  <div
                    style={{
                      ...styles.connector,
                      background: stage.status === 'done' || stage.status === 'skipped'
                        ? 'var(--color-success)'
                        : 'var(--color-border)',
                    }}
                  />
                )}
              </div>

              {/* Content */}
              <div
                style={{
                  ...styles.content,
                  background: isActive ? 'rgba(47,111,212,0.04)' : 'transparent',
                  borderRadius: 'var(--radius-sm)',
                  marginBottom: i < stages.length - 1 ? 0 : 0,
                }}
              >
                <span
                  style={{
                    ...styles.stageLabel,
                    color: stage.status === 'idle'
                      ? 'var(--color-text-muted)'
                      : 'var(--color-text-primary)',
                    fontWeight: isActive ? 600 : 500,
                  }}
                >
                  {stage.label}
                </span>
                {stage.detail && (
                  <span style={styles.stageDetail}>{stage.detail}</span>
                )}
              </div>

              {/* Badge */}
              <div style={styles.badgeCol}>
                {isActive && (
                  <span style={styles.badgeRunning}>running</span>
                )}
                {stage.status === 'skipped' && (
                  <span style={styles.badgeCached}>cached</span>
                )}
                {stage.status === 'done' && (
                  <span style={styles.badgeDone}>done</span>
                )}
              </div>
            </div>
          );
        })}
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
    padding: '18px 20px',
    animation: 'fadeIn 0.2s ease',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
  },
  label: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-text-muted)',
  },
  counter: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--color-text-muted)',
    fontFamily: 'var(--font-mono)',
  },
  stages: {
    display: 'flex',
    flexDirection: 'column' as const,
  },
  row: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 10,
    minHeight: 36,
  },
  track: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    flexShrink: 0,
    paddingTop: 6,
  },
  connector: {
    width: 2,
    flex: 1,
    minHeight: 10,
    borderRadius: 1,
    marginTop: 4,
    transition: 'background 0.3s',
  },
  content: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 1,
    padding: '4px 6px',
    transition: 'background 0.2s',
  },
  stageLabel: {
    fontSize: 13,
    lineHeight: 1.4,
    transition: 'color 0.2s, font-weight 0.1s',
  },
  stageDetail: {
    fontSize: 11,
    color: 'var(--color-text-muted)',
  },
  badgeCol: {
    paddingTop: 6,
    flexShrink: 0,
    width: 52,
    display: 'flex',
    justifyContent: 'flex-end',
  },
  badgeRunning: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-accent)',
    background: 'var(--color-accent-subtle)',
    border: '1px solid #c7d9f5',
    padding: '2px 7px',
    borderRadius: 20,
  },
  badgeCached: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-text-muted)',
    background: 'var(--color-surface-dim)',
    border: '1px solid var(--color-border)',
    padding: '2px 7px',
    borderRadius: 20,
  },
  badgeDone: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-success)',
    background: 'var(--color-success-bg)',
    border: '1px solid #86efac',
    padding: '2px 7px',
    borderRadius: 20,
  },
};

export default PipelineProgress;
