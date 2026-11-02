import Link from 'next/link';
import '../../phase2.css';

type Observation = { indicator_id: string; label: string; unit: string; status: string; latest_period_end?: string; value?: number; days_behind_as_of?: number; observation_count?: number; latest_monthly_return_pct?: number; latest_monthly_return_period_end?: string };
type Evidence = { stance: string; statement: string; basis: string };
type Condition = { condition: string; status: string };
type Implication = { horizon: string; scenario: string; would_strengthen: string; would_weaken: string };
type FlowPoint = { date: string; fpi_net: number | null; dii_net: number | null; fpi_roll5: number | null; dii_roll5: number | null; fpi_provider?: string; dii_provider?: string };
type NiftyPoint = { date: string; close: number; normalized: number; provider?: string };
type SipPoint = { period_end: string; value: number; unit: string; provider?: string; mom_growth_pct: number | null };
type ReflexivitySeries = { range: string; start: string; flows: FlowPoint[]; nifty: NiftyPoint[]; sip: SipPoint[] };
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
  series?: ReflexivitySeries;
};
const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
const fmt = (n: number | null | undefined, digits = 1) => n == null ? 'N/A' : n.toLocaleString('en-IN', { maximumFractionDigits: digits });

function Panel({ title, children, note }: { title: string; children?: React.ReactNode; note?: string }) {
  return <section className="panel" aria-label={title}><h2>{title}</h2>{note && <p className="muted">{note}</p>}{children}</section>;
}

const STANCE_LABEL: Record<string, string> = { supporting: 'Supporting the hypothesis', contradictory: 'Contradicting the hypothesis', insufficient: 'Insufficient to evaluate' };

function FlowChart({ rows, rolling }: { rows: FlowPoint[]; rolling: boolean }) {
  const values = rows.flatMap(r => rolling ? [r.fpi_roll5, r.dii_roll5] : [r.fpi_net, r.dii_net]).filter((v): v is number => v != null);
  if (values.length < 2) return <div className="empty">DATA UNAVAILABLE · insufficient stored sessions</div>;
  const min = Math.min(0, ...values); const max = Math.max(0, ...values); const span = max - min || 1;
  const y = (v: number) => 90 - (v - min) / span * 70;
  const zero = y(0);
  const slot = 100 / rows.length;
  return <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="FPI and DII daily net equity flows, negative flows below zero">
    <line x1="0" y1={zero} x2="100" y2={zero} stroke="#8ea0b8" strokeWidth=".6" vectorEffect="non-scaling-stroke"/>
    {rows.map((row, i) => {
      const fpi = rolling ? row.fpi_roll5 : row.fpi_net;
      const dii = rolling ? row.dii_roll5 : row.dii_net;
      return <g key={row.date}>
        {fpi != null && <rect x={i * slot + slot * .06} y={y(Math.max(fpi, 0))} width={slot * .4} height={Math.max(Math.abs(y(fpi) - zero), .3)} fill="#d27c75"><title>{`${row.date} · FPI ${fmt(fpi, 0)} INR crore${row.fpi_provider ? ` · ${row.fpi_provider}` : ''}`}</title></rect>}
        {dii != null && <rect x={i * slot + slot * .52} y={y(Math.max(dii, 0))} width={slot * .4} height={Math.max(Math.abs(y(dii) - zero), .3)} fill="#63d7d0"><title>{`${row.date} · DII ${fmt(dii, 0)} INR crore${row.dii_provider ? ` · ${row.dii_provider}` : ''}`}</title></rect>}
      </g>;
    })}
  </svg><div className="chart-axis"><span>{rows[0].date}</span><span>{rolling ? 'rolling 5-session net' : 'daily net'} · INR crore</span><span>{rows[rows.length - 1].date}</span></div></div>;
}

function NiftyChart({ rows }: { rows: NiftyPoint[] }) {
  if (rows.length < 2) return <div className="empty">DATA UNAVAILABLE · insufficient stored sessions</div>;
  const values = rows.map(r => r.normalized);
  const min = Math.min(100, ...values); const max = Math.max(100, ...values); const span = max - min || 1;
  const x = (i: number) => i / (rows.length - 1) * 100;
  const y = (v: number) => 90 - (v - min) / span * 70;
  const points = values.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(' ');
  return <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Nifty 50 closing levels rebased to 100 at period start">
    <line x1="0" y1={y(100)} x2="100" y2={y(100)} stroke="#d7b16d" strokeWidth=".8" strokeDasharray="3 2" vectorEffect="non-scaling-stroke"/>
    <polyline fill="none" stroke="#9ce8e1" strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={points}/>
    {rows.map((r, i) => <circle key={r.date} cx={x(i)} cy={y(r.normalized)} r=".55" fill="#9ce8e1"><title>{`${r.date}: close ${fmt(r.close, 2)} → rebased ${fmt(r.normalized, 2)}${r.provider ? ` · ${r.provider}` : ''}`}</title></circle>)}
  </svg><div className="chart-axis"><span>{rows[0].date}</span><span>close rebased to 100 at {rows[0].date} · index points</span><span>{rows[rows.length - 1].date}</span></div></div>;
}

function SipChart({ rows, growth }: { rows: SipPoint[]; growth: boolean }) {
  if (!rows.length) return <div className="empty">DATA UNAVAILABLE · no monthly observations stored</div>;
  if (growth) {
    const points = rows.filter(r => r.mom_growth_pct != null);
    if (points.length < 2) return <div className="empty">DATA UNAVAILABLE · growth needs two consecutive stored months (no interpolation)</div>;
    const values = points.map(r => r.mom_growth_pct as number);
    const min = Math.min(0, ...values); const max = Math.max(0, ...values); const span = max - min || 1;
    const x = (i: number) => i / (points.length - 1) * 100;
    const y = (v: number) => 90 - (v - min) / span * 70;
    const zero = y(0);
    return <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Month-over-month SIP contribution growth">
      <line x1="0" y1={zero} x2="100" y2={zero} stroke="#8ea0b8" strokeWidth=".6" vectorEffect="non-scaling-stroke"/>
      <polyline fill="none" stroke="#c9a84c" strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={points.map((r, i) => `${x(i).toFixed(2)},${y(r.mom_growth_pct as number).toFixed(2)}`).join(' ')}/>
      {points.map((r, i) => <circle key={r.period_end} cx={x(i)} cy={y(r.mom_growth_pct as number)} r=".55" fill="#c9a84c"><title>{`${r.period_end}: MoM growth ${fmt(r.mom_growth_pct, 2)}%`}</title></circle>)}
    </svg><div className="chart-axis"><span>{points[0].period_end}</span><span>MoM growth · %</span><span>{points[points.length - 1].period_end}</span></div></div>;
  }
  const values = rows.map(r => r.value);
  const min = Math.min(0, ...values); const max = Math.max(...values); const span = max - min || 1;
  const slot = 100 / rows.length;
  const y = (v: number) => 90 - (v - min) / span * 70;
  const zero = y(0);
  return <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Monthly SIP contributions in INR crore">
    <line x1="0" y1={zero} x2="100" y2={zero} stroke="#8ea0b8" strokeWidth=".6" vectorEffect="non-scaling-stroke"/>
    {rows.map((r, i) => <rect key={r.period_end} x={i * slot + slot * .15} y={y(Math.max(r.value, 0))} width={slot * .7} height={Math.max(Math.abs(y(r.value) - zero), .3)} fill="#9ce8e1"><title>{`${r.period_end}: ${fmt(r.value, 0)} INR crore${r.provider ? ` · ${r.provider}` : ''}`}</title></rect>)}
  </svg><div className="chart-axis"><span>{rows[0].period_end}</span><span>monthly contribution · INR crore</span><span>{rows[rows.length - 1].period_end}</span></div></div>;
}

export default async function ReflexivityCycle({ searchParams }: { searchParams: Promise<{ as_of?: string; range?: string; flow_mode?: string; sip_mode?: string }> }) {
  const params = await searchParams;
  const apiBase = api;
  const token = process.env.RESEARCH_OPERATOR_TOKEN;
  const query = new URLSearchParams(); if (params.as_of) query.set('as_of', params.as_of); if (params.range) query.set('range', params.range);
  const flowRolling = params.flow_mode === 'rolling5';
  const sipGrowth = params.sip_mode === 'growth';
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
    <Panel title="Historical charts" note={`Actual stored observations for the selected window (from ${data.series?.start || 'period start'}). Observations only — no interpolation, no synthetic values; the interpretation panels below are kept separate.`}>
      <form className="filters" action="/intelligence/reflexivity" method="get" aria-label="Chart range and display controls">
        {params.as_of ? <input type="hidden" name="as_of" value={params.as_of} /> : null}
        <label>Range <select name="range" defaultValue={params.range || 'since_april'}><option value="1m">1 month</option><option value="3m">3 months</option><option value="since_april">Since 1 Apr 2026</option></select></label>
        <label>Flows <select name="flow_mode" defaultValue={params.flow_mode || 'daily'}><option value="daily">Daily net</option><option value="rolling5">Rolling 5-session total</option></select></label>
        <label>SIP <select name="sip_mode" defaultValue={params.sip_mode || 'level'}><option value="level">Monthly level</option><option value="growth">MoM growth</option></select></label>
        <button type="submit">Apply</button>
      </form>
      {data.series && <div className="chart-grid">
        <section aria-label="Institutional flows chart"><h3>Institutional flows</h3><FlowChart rows={data.series.flows} rolling={flowRolling} /></section>
        <section aria-label="Market performance chart"><h3>Market performance</h3><NiftyChart rows={data.series.nifty} /></section>
        <section aria-label="Household participation chart"><h3>Household participation</h3><SipChart rows={data.series.sip} growth={sipGrowth} /></section>
      </div>}
      <p className="muted">Synchronized window · flows and SIP in INR crore (negative net flows plot below zero) · market closes rebased to 100 at the period start. Missing months and sessions are absent, never bridged.</p>
    </Panel>
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
