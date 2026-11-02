import Link from 'next/link';
import '../../phase2.css';

type Observation = { indicator_id: string; label: string; unit: string; status: string; latest_period_end?: string; value?: number; days_behind_as_of?: number; observation_count?: number; latest_monthly_return_pct?: number; latest_monthly_return_period_end?: string };
type Evidence = { stance: string; statement: string; basis: string };
type Condition = { condition: string; status: string };
type Implication = { horizon: string; scenario: string; would_strengthen: string; would_weaken: string };
type View = {
  as_of: string;
  state: string;
  cycle: string;
  research_question: string;
  hypothesis: string;
  reason?: string;
  observations: Record<string, Observation>;
  evidence: Evidence[];
  inflection: Condition[];
  implications: Implication[];
  limitation: string;
  vintage_mode?: string;
};
const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
const fmt = (n: number | null | undefined, digits = 1) => n == null ? 'N/A' : n.toLocaleString('en-IN', { maximumFractionDigits: digits });

function Panel({ title, children, note }: { title: string; children?: React.ReactNode; note?: string }) {
  return <section className="panel" aria-label={title}><h2>{title}</h2>{note && <p className="muted">{note}</p>}{children}</section>;
}

const STANCE_LABEL: Record<string, string> = { supporting: 'Supporting the hypothesis', contradictory: 'Contradicting the hypothesis', insufficient: 'Insufficient to evaluate' };

export default async function ReflexivityCycle({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const params = await searchParams;
  const apiBase = api;
  const token = process.env.RESEARCH_OPERATOR_TOKEN;
  const query = new URLSearchParams(); if (params.as_of) query.set('as_of', params.as_of);
  let data: View | null = null;
  if (token) {
    const res = await fetch(`${apiBase}/api/v1/research/reflexivity-cycle?${query}`, { headers: { 'X-Admin-Token': token }, cache: 'no-store' }).catch(() => null);
    if (res?.ok) data = await res.json();
  }
  if (!data) {
    return <main className="container">
      <section className="panel"><h2>Reflexivity research cycle</h2><p>Private operator access is not configured for this environment, so no cycle view is shown. Existing verified and demonstration monitors remain available. No live macro conclusion is implied.</p></section>
    </main>;
  }
  const observations = data.observations || {};
  const groups: { stance: string; items: Evidence[] }[] = ['supporting', 'contradictory', 'insufficient'].map(stance => ({ stance, items: data.evidence.filter(e => e.stance === stance) }));
  return <main className="container">
    <header className="header"><div><div className="eyebrow">SMART HEDGE / PRIVATE RESEARCH</div><h1>Reflexivity research cycle</h1><p className="subtitle">Domestic equity flows and market reflexivity · hypothesis, evidence, inflection, implications</p><Link href="/intelligence">Cycle intelligence →</Link> · <Link href="/intelligence/capital-flows">Capital-flow investigation →</Link> · <Link href="/intelligence/discovery">Research notes and investigations →</Link></div><div className="header-right"><strong className="live-label">HYPOTHESIS UNDER INVESTIGATION</strong><span>{data.as_of}{data.vintage_mode ? ` · ${data.vintage_mode}` : ''}</span></div></header>
    <p className="caption">Research question: {data.research_question}</p>
    <Panel title="A. Current observations" note="Actual stored observations only. Missing or stale inputs are identified, never substituted or zero-filled.">
      {(['fpi', 'dii', 'sip', 'returns'] as const).map(key => {
        const obs = observations[key];
        if (!obs) return <p key={key} className="muted">{key}: no summary available.</p>;
        if (obs.status === 'missing') return <p key={key} className="result">{obs.label}: <strong>DATA UNAVAILABLE</strong> — no observations stored for this evaluation window.</p>;
        return <p key={key} className="result">{obs.label}: {fmt(obs.value, obs.unit === 'index points' ? 2 : 0)} {obs.unit} · period ending {obs.latest_period_end} · <strong className={obs.status === 'stale' ? 'muted' : ''}>{obs.status.toUpperCase()}</strong> ({obs.days_behind_as_of} days behind as-of){key === 'returns' && obs.latest_monthly_return_pct != null ? ` · latest derived monthly return ${fmt(obs.latest_monthly_return_pct, 2)}% (${obs.latest_monthly_return_period_end})` : ''}</p>;
      })}
    </Panel>
    <Panel title="B. Proposed feedback mechanism" note="A hypothesis to investigate — not an established causal relationship.">
      <p className="result">Market performance → investor allocation decisions → domestic equity flows (DII + household SIP) → market demand → market performance.</p>
      <p className="muted">{data.hypothesis}</p>
    </Panel>
    <Panel title="C. Supporting, contradictory and insufficient evidence" note="Classification is descriptive: no conclusion is manufactured from absence, and co-occurrence is never promoted to causation.">
      {data.evidence.length ? groups.map(g => g.items.length ? <div key={g.stance}><p><strong>{STANCE_LABEL[g.stance]}:</strong></p>{g.items.map((e, i) => <p key={i} className={g.stance === 'insufficient' ? 'muted' : 'result'}>· {e.statement} <span className="muted">Basis: {e.basis}</span></p>)}</div> : null) : <p className="muted">No evidence items classified.</p>}
    </Panel>
    <Panel title="D. Possible inflection — conditions to monitor" note="Conditions to monitor, not automatic predictions. A condition is marked observed only when stored evidence already shows it.">
      {data.inflection.map((c, i) => <p key={i} className="result">· {c.condition} <strong>{c.status}</strong></p>)}
    </Panel>
    <Panel title="E. Investment implications — conditional scenarios" note="Conditional narratives only. No price targets, probabilities or buy/sell signals are generated.">
      {data.implications.map(imp => <details className="alert-card" key={imp.horizon}><summary><strong>Next {imp.horizon}</strong></summary><p>{imp.scenario}</p><p className="muted">Would strengthen the thesis: {imp.would_strengthen}</p><p className="muted">Would weaken the thesis: {imp.would_weaken}</p></details>)}
    </Panel>
    <Panel title="Recording research notes" note="This screen is read-only; hypotheses and evidence are recorded through the existing research workflow.">
      <p className="muted">Open <Link href="/intelligence/discovery">Persistent anomaly discovery</Link> to freeze a snapshot or begin an investigation using the existing evidence and interpretation capabilities.</p>
    </Panel>
    <Panel title="Limitations"><p className="result limitation">{data.limitation}</p></Panel>
    <form className="filters" action="/intelligence/reflexivity" method="get" aria-label="Cycle view filters"><label>As-of timestamp (ISO) <input type="text" name="as_of" defaultValue={params.as_of || ''} /></label><button type="submit">Apply</button></form>
  </main>;
}
