import React from 'react';

// ── Types ─────────────────────────────────────────────────────────────────
// Every field maps 1-to-1 to backend output keys — swap mock data for API
// response and the UI just works.

export interface SgRNACandidate {
  guide_id: string;
  sequence: string;
  efficiency_score: number;  // GC content 0–1
  pam: string;
}

export interface ReviewFlag {
  severity: 'info' | 'warning' | 'critical';
  category: string;
  issue: string;
  recommendation: string;
  patchable: boolean;
}

export interface FeasibilityFlag {
  severity: 'warning' | 'blocker';
  message: string;
}

export interface PipelineResult {
  // Hypothesis
  hypothesis_text: string;

  // Parsed experiment design
  gene: string;
  cell_line: string;
  edit_type: string;
  phenotype: string;
  system_context: string;
  assumptions: string[];

  // Feasibility
  feasibility_verdict: 'pass' | 'warn' | 'block';
  feasibility_flags: FeasibilityFlag[];

  // sgRNAs
  sgrna_candidates: SgRNACandidate[];

  // Protocol
  protocol_steps: { step_number: number; title: string; duration_hours: number | null }[];
  total_duration_days: number;
  validation_assay: string;
  transfection_method: string;

  // Scientific review
  verdict: string;
  flags: ReviewFlag[];
  review_summary: string;
  patches_applied: string[];

  // Execution timeline
  timeline: { day: number; activity: string }[];
  reagents: { item: string; purpose: string }[];

  // Literature
  literature_sources: { title: string; journal: string; year: string }[];
}

interface ResultsPanelProps {
  result: PipelineResult | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────

const VERDICT_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  approve:               { label: 'Approved',               color: 'var(--color-success)', bg: 'var(--color-success-bg)', border: '#86efac' },
  approve_with_warnings: { label: 'Approved with Warnings', color: 'var(--color-warning)', bg: 'var(--color-warning-bg)', border: '#fcd34d' },
  revise:                { label: 'Revise',                 color: 'var(--color-warning)', bg: 'var(--color-warning-bg)', border: '#fcd34d' },
  major_revision:        { label: 'Major Revision',         color: 'var(--color-critical)', bg: 'var(--color-critical-bg)', border: '#fca5a5' },
};

const FEASIBILITY_CONFIG = {
  pass: { label: 'Feasible', color: 'var(--color-success)', bg: 'var(--color-success-bg)', border: '#86efac', icon: '✓' },
  warn: { label: 'Proceed with Caution', color: 'var(--color-warning)', bg: 'var(--color-warning-bg)', border: '#fcd34d', icon: '!' },
  block: { label: 'Blocked', color: 'var(--color-critical)', bg: 'var(--color-critical-bg)', border: '#fca5a5', icon: '✗' },
};

const SEVERITY_CONFIG = {
  critical: { color: 'var(--color-critical)', bg: 'var(--color-critical-bg)', border: '#fca5a5', icon: '✗' },
  warning:  { color: 'var(--color-warning)',  bg: 'var(--color-warning-bg)',  border: '#fcd34d', icon: '!' },
  info:     { color: 'var(--color-info)',     bg: 'var(--color-info-bg)',     border: '#93c5fd', icon: 'i' },
};

function formatHours(hours: number): string {
  if (hours >= 24) {
    const days = hours / 24;
    return `${days % 1 === 0 ? days : days.toFixed(1)}d`;
  }
  return `${hours}h`;
}

// ── Card shell ────────────────────────────────────────────────────────────

const Card: React.FC<{
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ title, badge, children, style }) => (
  <div style={{ ...s.card, ...style }}>
    <div style={s.cardHeader}>
      <span style={s.cardTitle}>{title}</span>
      {badge}
    </div>
    <div style={s.cardBody}>{children}</div>
  </div>
);

// ── 1. Hypothesis card ────────────────────────────────────────────────────

const HypothesisCard: React.FC<{ result: PipelineResult }> = ({ result }) => (
  <Card title="Hypothesis">
    <blockquote style={s.hypothesis}>
      "{result.hypothesis_text}"
    </blockquote>
  </Card>
);

// ── 2. Parsed Experiment Design card ─────────────────────────────────────

const ExperimentDesignCard: React.FC<{ result: PipelineResult }> = ({ result }) => (
  <Card title="Parsed Experiment Design">
    <div style={s.designGrid}>
      <DesignField label="Target Gene"        value={result.gene} mono />
      <DesignField label="Cell Line"          value={result.cell_line} />
      <DesignField label="Edit Type"          value={result.edit_type} />
      <DesignField label="Transfection"       value={result.transfection_method} />
      <DesignField label="Phenotype"          value={result.phenotype} span />
      <DesignField label="System Context"     value={result.system_context} span />
    </div>
    {result.assumptions.length > 0 && (
      <div style={{ marginTop: 14 }}>
        <p style={s.fieldLabel}>Assumptions Made</p>
        <ul style={s.assumptionList}>
          {result.assumptions.map((a, i) => (
            <li key={i} style={s.assumptionItem}>
              <span style={s.bulletDot} />
              <span style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>{a}</span>
            </li>
          ))}
        </ul>
      </div>
    )}
  </Card>
);

const DesignField: React.FC<{ label: string; value: string; mono?: boolean; span?: boolean }> = ({
  label, value, mono, span,
}) => (
  <div style={span ? { gridColumn: '1 / -1' } : {}}>
    <p style={s.fieldLabel}>{label}</p>
    <p style={mono ? { ...s.fieldValue, fontFamily: 'var(--font-mono)', fontSize: 13 } : s.fieldValue}>
      {value}
    </p>
  </div>
);

// ── 3. Feasibility card ───────────────────────────────────────────────────

const FeasibilityCard: React.FC<{ result: PipelineResult }> = ({ result }) => {
  const cfg = FEASIBILITY_CONFIG[result.feasibility_verdict];
  return (
    <Card
      title="Feasibility Verdict"
      badge={
        <span style={{ ...s.verdictPill, color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.border}` }}>
          {cfg.icon} {cfg.label}
        </span>
      }
    >
      {result.feasibility_flags.length === 0 ? (
        <p style={s.emptyInline}>No feasibility concerns flagged.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {result.feasibility_flags.map((f, i) => {
            const fc = f.severity === 'blocker' ? SEVERITY_CONFIG.critical : SEVERITY_CONFIG.warning;
            return (
              <div
                key={i}
                style={{
                  padding: '8px 12px',
                  borderRadius: 'var(--radius-sm)',
                  background: fc.bg,
                  border: `1px solid ${fc.border}`,
                  display: 'flex',
                  gap: 8,
                  alignItems: 'flex-start',
                }}
              >
                <span style={{ color: fc.color, fontWeight: 700, fontSize: 12, flexShrink: 0, marginTop: 1 }}>
                  {fc.icon}
                </span>
                <span style={{ color: 'var(--color-text-primary)', fontSize: 13, lineHeight: 1.5 }}>
                  {f.message}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
};

// ── 4. Selected sgRNAs table ──────────────────────────────────────────────

const SgRNATableCard: React.FC<{ result: PipelineResult }> = ({ result }) => (
  <Card title="Candidate sgRNAs">
    <div style={{ overflowX: 'auto' }}>
      <table style={s.table}>
        <thead>
          <tr>
            {['Rank', 'Guide ID', 'Sequence (5′→3′)', 'GC %', 'PAM'].map((h) => (
              <th key={h} style={s.th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.sgrna_candidates.map((g, i) => (
            <tr key={g.guide_id} style={i % 2 === 0 ? {} : { background: 'var(--color-surface-dim)' }}>
              <td style={s.td}>
                <span style={s.rankBadge}>#{i + 1}</span>
              </td>
              <td style={{ ...s.td, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)' }}>
                {g.guide_id}
              </td>
              <td style={{ ...s.td, fontFamily: 'var(--font-mono)', fontSize: 13, letterSpacing: '0.04em' }}>
                {g.sequence}
              </td>
              <td style={s.td}>
                <GcBar value={g.efficiency_score} />
              </td>
              <td style={s.td}>
                <span style={s.pamBadge}>{g.pam}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </Card>
);

const GcBar: React.FC<{ value: number }> = ({ value }) => {
  const pct = Math.round(value * 100);
  const optimal = pct >= 40 && pct <= 70;
  const barColor = optimal ? 'var(--color-success)' : 'var(--color-warning)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 80 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--color-border)', borderRadius: 99 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: barColor, borderRadius: 99 }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 600, color: optimal ? 'var(--color-success)' : 'var(--color-warning)', minWidth: 28 }}>
        {pct}%
      </span>
    </div>
  );
};

// ── 5. Protocol Summary card ──────────────────────────────────────────────

const ProtocolSummaryCard: React.FC<{ result: PipelineResult }> = ({ result }) => (
  <Card title="Protocol Summary">
    <div style={s.metaRow}>
      <MetaChip label="Total Duration"  value={`${result.total_duration_days} days`} />
      <MetaChip label="Validation"      value={result.validation_assay} />
      <MetaChip label="Cell Line"       value={result.cell_line} />
      <MetaChip label="Transfection"    value={result.transfection_method} />
    </div>

    <div style={{ marginTop: 20 }}>
      {result.protocol_steps.map((step, i) => {
        const isLast = i === result.protocol_steps.length - 1;
        return (
          <div key={step.step_number} style={{ display: 'flex', gap: 0 }}>
            <div style={s.stepTrack}>
              <div style={s.stepBubble}>{step.step_number}</div>
              {!isLast && <div style={s.stepConnector} />}
            </div>
            <div style={{ paddingLeft: 14, paddingBottom: isLast ? 0 : 20, flex: 1, paddingTop: 2 }}>
              <p style={s.stepTitle}>{step.title}</p>
              {step.duration_hours != null && (
                <p style={s.stepDuration}>{formatHours(step.duration_hours)}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  </Card>
);

const MetaChip: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={s.metaChip}>
    <p style={s.metaChipLabel}>{label}</p>
    <p style={s.metaChipValue}>{value}</p>
  </div>
);

// ── 6. Scientific Review card ─────────────────────────────────────────────

const ScientificReviewCard: React.FC<{ result: PipelineResult }> = ({ result }) => {
  const vc = VERDICT_CONFIG[result.verdict] ?? VERDICT_CONFIG.revise;
  const criticals = result.flags.filter((f) => f.severity === 'critical');
  const warnings  = result.flags.filter((f) => f.severity === 'warning');
  const infos     = result.flags.filter((f) => f.severity === 'info');

  return (
    <Card
      title="Scientific Review"
      badge={
        <span style={{ ...s.verdictPill, color: vc.color, background: vc.bg, border: `1px solid ${vc.border}` }}>
          {vc.label}
        </span>
      }
    >
      {/* Summary */}
      <p style={{ color: 'var(--color-text-secondary)', fontSize: 14, lineHeight: 1.7, marginBottom: 20 }}>
        {result.review_summary}
      </p>

      {/* Flag counts */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        {[
          { count: criticals.length, label: 'Critical', ...SEVERITY_CONFIG.critical },
          { count: warnings.length,  label: 'Warning',  ...SEVERITY_CONFIG.warning  },
          { count: infos.length,     label: 'Info',     ...SEVERITY_CONFIG.info     },
        ].filter(({ count }) => count > 0).map(({ count, label, color, bg, border }) => (
          <span key={label} style={{ ...s.countPill, color, background: bg, border: `1px solid ${border}` }}>
            {count} {label}
          </span>
        ))}
        {result.patches_applied.length > 0 && (
          <span style={{ ...s.countPill, color: 'var(--color-success)', background: 'var(--color-success-bg)', border: '1px solid #86efac' }}>
            {result.patches_applied.length} auto-patched
          </span>
        )}
      </div>

      {/* Flags */}
      {[
        { label: 'Critical Issues', flags: criticals, sev: 'critical' as const },
        { label: 'Warnings',        flags: warnings,  sev: 'warning'  as const },
        { label: 'Info',            flags: infos,     sev: 'info'     as const },
      ].map(({ label, flags, sev }) =>
        flags.length > 0 ? (
          <div key={label} style={{ marginBottom: 16 }}>
            <p style={{ ...s.fieldLabel, marginBottom: 8 }}>{label}</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {flags.map((f, i) => {
                const fc = SEVERITY_CONFIG[sev];
                return (
                  <div
                    key={i}
                    style={{
                      padding: '10px 14px',
                      borderRadius: 'var(--radius-md)',
                      background: fc.bg,
                      border: `1px solid ${fc.border}`,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' as const, color: fc.color }}>
                        {f.category}
                      </span>
                      {f.patchable && (
                        <span style={s.patchedTag}>auto-patched</span>
                      )}
                    </div>
                    <p style={{ fontSize: 13, color: 'var(--color-text-primary)', marginBottom: 4, lineHeight: 1.5 }}>
                      {f.issue}
                    </p>
                    <p style={{ fontSize: 12, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                      → {f.recommendation}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null
      )}
    </Card>
  );
};

// ── 7. Execution Timeline card ────────────────────────────────────────────

const ExecutionTimelineCard: React.FC<{ result: PipelineResult }> = ({ result }) => {
  const maxDay = result.total_duration_days;

  // Phase definitions derived from protocol steps for the bar chart
  const phases = buildPhases(result.protocol_steps);

  return (
    <Card title="Execution Timeline">
      {/* Gantt-style phase bars */}
      <div style={{ marginBottom: 28 }}>
        <p style={{ ...s.fieldLabel, marginBottom: 12 }}>Phase Overview ({maxDay} days)</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {phases.map((phase) => {
            const leftPct  = ((phase.startDay - 1) / maxDay) * 100;
            const widthPct = Math.max((phase.durationDays / maxDay) * 100, 2);
            return (
              <div key={phase.title} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={s.phaseLabel}>{phase.title}</span>
                <div style={{ flex: 1, position: 'relative' as const, height: 20, background: 'var(--color-surface-dim)', borderRadius: 99, border: '1px solid var(--color-border)' }}>
                  <div
                    style={{
                      position: 'absolute' as const,
                      left: `${leftPct}%`,
                      width: `${widthPct}%`,
                      height: '100%',
                      background: phase.color,
                      borderRadius: 99,
                      opacity: 0.85,
                    }}
                  />
                </div>
                <span style={s.phaseDays}>{phase.durationDays}d</span>
              </div>
            );
          })}
        </div>

        {/* Day axis */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, paddingLeft: 112, paddingRight: 32 }}>
          {[1, Math.round(maxDay * 0.25), Math.round(maxDay * 0.5), Math.round(maxDay * 0.75), maxDay].map((d) => (
            <span key={d} style={{ fontSize: 10, color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
              d{d}
            </span>
          ))}
        </div>
      </div>

      {/* Day-by-day events */}
      <p style={{ ...s.fieldLabel, marginBottom: 12 }}>Day-by-Day Activities</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {result.timeline.map((event, i) => {
          const isLast = i === result.timeline.length - 1;
          const nextDay = result.timeline[i + 1]?.day;
          const gap = nextDay ? nextDay - event.day : 0;
          return (
            <div key={event.day} style={{ display: 'flex', gap: 0 }}>
              {/* Left track */}
              <div style={s.timelineTrack}>
                <div style={s.timelineDot} />
                {!isLast && (
                  <div style={{
                    ...s.timelineConnector,
                    height: gap > 1 ? 36 : 24,
                    borderLeft: gap > 3 ? '2px dashed var(--color-border)' : '2px solid var(--color-border)',
                  }} />
                )}
              </div>

              {/* Event content */}
              <div style={{ paddingLeft: 12, paddingBottom: isLast ? 0 : (gap > 1 ? 20 : 12), flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                  <span style={s.dayBadge}>Day {event.day}</span>
                  {gap > 1 && (
                    <span style={s.gapNote}>{gap - 1}d gap</span>
                  )}
                </div>
                <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                  {event.activity}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
};

// Build phase bars from protocol steps
function buildPhases(steps: PipelineResult['protocol_steps']) {
  const PHASE_COLORS = [
    '#3b82f6', '#8b5cf6', '#06b6d4', '#f59e0b',
    '#10b981', '#f43f5e', '#6366f1', '#ec4899',
  ];
  let cursor = 1;
  return steps.map((step, i) => {
    const durationDays = step.duration_hours != null
      ? Math.max(step.duration_hours / 24, 0.5)
      : 1;
    const phase = {
      title: step.title,
      startDay: cursor,
      durationDays: parseFloat(durationDays.toFixed(1)),
      color: PHASE_COLORS[i % PHASE_COLORS.length],
    };
    cursor += durationDays;
    return phase;
  });
}

// ── Main component ────────────────────────────────────────────────────────

const ResultsPanel: React.FC<ResultsPanelProps> = ({ result }) => {
  if (!result) {
    return (
      <div style={{ ...s.card, ...s.emptyState }}>
        <div style={s.emptyHex}>⬡</div>
        <p style={s.emptyTitle}>No results yet</p>
        <p style={s.emptyBody}>
          Enter a hypothesis above and click <strong>Run Pipeline</strong> to generate a full CRISPR
          experiment design, or <strong>Load from Cache</strong> to replay a previous result.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Row 1: Hypothesis — full width */}
      <HypothesisCard result={result} />

      {/* Row 2: Experiment Design + Feasibility — side by side */}
      <div style={s.twoCol}>
        <ExperimentDesignCard result={result} />
        <FeasibilityCard      result={result} />
      </div>

      {/* Row 3: sgRNAs table — full width */}
      <SgRNATableCard result={result} />

      {/* Row 4: Protocol Summary — full width */}
      <ProtocolSummaryCard result={result} />

      {/* Row 5: Scientific Review — full width */}
      <ScientificReviewCard result={result} />

      {/* Row 6: Execution Timeline — full width */}
      <ExecutionTimelineCard result={result} />
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  // Card
  card: {
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-lg)',
    boxShadow: 'var(--shadow-sm)',
    overflow: 'hidden',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '14px 20px',
    borderBottom: '1px solid var(--color-border)',
    background: 'var(--color-surface-dim)',
  },
  cardTitle: {
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: '0.07em',
    textTransform: 'uppercase',
    color: 'var(--color-text-secondary)',
  },
  cardBody: {
    padding: '20px',
  },

  // Empty state
  emptyState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '64px 40px',
    textAlign: 'center',
    gap: 12,
  },
  emptyHex: {
    fontSize: 36,
    color: 'var(--color-text-muted)',
    opacity: 0.35,
    lineHeight: 1,
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: 600,
    color: 'var(--color-text-secondary)',
  },
  emptyBody: {
    fontSize: 13,
    color: 'var(--color-text-muted)',
    maxWidth: 420,
    lineHeight: 1.75,
  },
  emptyInline: {
    fontSize: 13,
    color: 'var(--color-text-muted)',
    fontStyle: 'italic',
  },

  // Layout
  twoCol: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
    gap: 16,
  },

  // Hypothesis
  hypothesis: {
    fontSize: 15,
    fontStyle: 'italic',
    color: 'var(--color-text-primary)',
    lineHeight: 1.75,
    borderLeft: '3px solid var(--color-accent)',
    paddingLeft: 16,
    margin: 0,
  },

  // Design grid
  designGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
    gap: '12px 20px',
  },
  fieldLabel: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.09em',
    textTransform: 'uppercase',
    color: 'var(--color-text-muted)',
    marginBottom: 3,
  },
  fieldValue: {
    fontSize: 14,
    fontWeight: 500,
    color: 'var(--color-text-primary)',
    lineHeight: 1.4,
  },
  assumptionList: {
    listStyle: 'none',
    display: 'flex',
    flexDirection: 'column',
    gap: 5,
    marginTop: 6,
  },
  assumptionItem: {
    display: 'flex',
    gap: 8,
    alignItems: 'flex-start',
  },
  bulletDot: {
    width: 5,
    height: 5,
    borderRadius: '50%',
    background: 'var(--color-text-muted)',
    flexShrink: 0,
    marginTop: 6,
  },

  // Pills / badges
  verdictPill: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: '0.06em',
    padding: '3px 10px',
    borderRadius: 20,
  },
  countPill: {
    fontSize: 11,
    fontWeight: 600,
    padding: '3px 10px',
    borderRadius: 20,
  },
  patchedTag: {
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: '0.06em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-success)',
    background: 'var(--color-success-bg)',
    padding: '2px 7px',
    borderRadius: 20,
    border: '1px solid #6ee7b7',
  },

  // sgRNA table
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 13,
  },
  th: {
    padding: '8px 12px',
    textAlign: 'left' as const,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-text-muted)',
    borderBottom: '1px solid var(--color-border)',
    background: 'var(--color-surface-dim)',
    whiteSpace: 'nowrap' as const,
  },
  td: {
    padding: '10px 12px',
    borderBottom: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
    verticalAlign: 'middle' as const,
  },
  rankBadge: {
    fontSize: 11,
    fontWeight: 700,
    color: 'var(--color-accent)',
    background: 'var(--color-accent-subtle)',
    border: '1px solid #c7d9f5',
    padding: '2px 7px',
    borderRadius: 20,
  },
  pamBadge: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--color-text-secondary)',
    background: 'var(--color-surface-dim)',
    border: '1px solid var(--color-border)',
    padding: '2px 7px',
    borderRadius: 20,
    fontFamily: 'var(--font-mono)',
  },

  // Protocol stepper
  metaRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 10,
    marginBottom: 4,
  },
  metaChip: {
    padding: '8px 14px',
    background: 'var(--color-surface-dim)',
    border: '1px solid var(--color-border)',
    borderRadius: 'var(--radius-md)',
  },
  metaChipLabel: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-text-muted)',
    marginBottom: 2,
  },
  metaChipValue: {
    fontSize: 13,
    fontWeight: 500,
    color: 'var(--color-text-primary)',
  },
  stepTrack: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    width: 28,
    flexShrink: 0,
  },
  stepBubble: {
    width: 26,
    height: 26,
    borderRadius: '50%',
    background: 'var(--color-accent-subtle)',
    border: '1.5px solid #c7d9f5',
    color: 'var(--color-accent)',
    fontSize: 11,
    fontWeight: 700,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  stepConnector: {
    width: 2,
    flex: 1,
    background: 'var(--color-border)',
    minHeight: 14,
    marginTop: 4,
  },
  stepTitle: {
    fontSize: 14,
    fontWeight: 500,
    color: 'var(--color-text-primary)',
  },
  stepDuration: {
    fontSize: 12,
    color: 'var(--color-text-muted)',
    marginTop: 2,
  },

  // Timeline
  timelineTrack: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    width: 16,
    flexShrink: 0,
    paddingTop: 5,
  },
  timelineDot: {
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: 'var(--color-accent)',
    border: '2px solid var(--color-accent-subtle)',
    flexShrink: 0,
  },
  timelineConnector: {
    width: 0,
    borderLeft: '2px solid var(--color-border)',
    marginTop: 3,
  },
  dayBadge: {
    fontSize: 11,
    fontWeight: 700,
    color: 'var(--color-accent)',
    background: 'var(--color-accent-subtle)',
    border: '1px solid #c7d9f5',
    padding: '2px 8px',
    borderRadius: 20,
    fontFamily: 'var(--font-mono)',
    flexShrink: 0,
  },
  gapNote: {
    fontSize: 10,
    color: 'var(--color-text-muted)',
    fontStyle: 'italic',
  },

  // Gantt
  phaseLabel: {
    fontSize: 11,
    fontWeight: 500,
    color: 'var(--color-text-secondary)',
    width: 100,
    flexShrink: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  phaseDays: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--color-text-muted)',
    fontFamily: 'var(--font-mono)',
    width: 24,
    textAlign: 'right' as const,
    flexShrink: 0,
  },
};

export default ResultsPanel;
