import type { ReactNode } from "react";

/** Consistent page title block: small eyebrow, serif title, descriptive subtitle. */
export function PageHeader({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return (
    <header className="page-header">
      {eyebrow && <span className="eyebrow">{eyebrow}</span>}
      <h1>{title}</h1>
      {children && <p className="page-sub">{children}</p>}
    </header>
  );
}

export function Section({ title, subtitle, id, children }: { title: string; subtitle?: ReactNode; id?: string; children: ReactNode }) {
  return (
    <section className="section" id={id}>
      <header>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </header>
      {children}
    </section>
  );
}

/** A statistic with an optional plain-language definition, so users know exactly what the number is. */
export function StatCard({ label, value, sub, note }: { label: string; value: ReactNode; sub?: ReactNode; note?: ReactNode }) {
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {sub && <span className="stat-sub">{sub}</span>}
      {note && <span className="stat-note">{note}</span>}
    </div>
  );
}

export function InfoNote({ variant = "info", title, children }: { variant?: "info" | "caution" | "limit"; title?: string; children: ReactNode }) {
  return (
    <aside className={`info-note ${variant === "info" ? "" : variant}`.trim()} role="note">
      {title && <strong>{title}</strong>}
      {children}
    </aside>
  );
}
