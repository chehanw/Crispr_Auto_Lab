import React from 'react';

const Header: React.FC = () => (
  <header style={styles.header}>
    <div style={styles.inner}>
      <div style={styles.logo}>
        <div style={styles.logoMark}>
          <span style={styles.logoMarkText}>AL</span>
        </div>
        <span style={styles.logoText}>AutoLab</span>
        <span style={styles.logoBadge}>CRISPR</span>
      </div>
      <p style={styles.tagline}>
        AI-assisted experimental design for CRISPR knockout studies
      </p>
    </div>
  </header>
);

const styles: Record<string, React.CSSProperties> = {
  header: {
    background: 'var(--color-surface)',
    borderBottom: '1px solid var(--color-border)',
    padding: '0 32px',
  },
  inner: {
    maxWidth: 1100,
    margin: '0 auto',
    padding: '14px 0',
    display: 'flex',
    alignItems: 'center',
    gap: 16,
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    flexShrink: 0,
  },
  logoMark: {
    width: 28,
    height: 28,
    borderRadius: 7,
    background: 'var(--color-accent)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoMarkText: {
    fontSize: 11,
    fontWeight: 800,
    color: '#fff',
    letterSpacing: '0.02em',
  },
  logoText: {
    fontSize: 17,
    fontWeight: 700,
    color: 'var(--color-text-primary)',
    letterSpacing: '-0.02em',
  },
  logoBadge: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.09em',
    textTransform: 'uppercase' as const,
    color: 'var(--color-accent)',
    background: 'var(--color-accent-subtle)',
    padding: '2px 7px',
    borderRadius: 20,
    border: '1px solid #c7d9f5',
  },
  tagline: {
    color: 'var(--color-text-muted)',
    fontSize: 13,
    borderLeft: '1px solid var(--color-border)',
    paddingLeft: 16,
    marginLeft: 2,
  },
};

export default Header;
