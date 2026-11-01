import Link from 'next/link';
import '../../phase2.css';

type Observation = { kind: string; id: number; series: string; period_end: string; value: number; source: string; source_reference: string; revision: string; published_at: string | null; retrieved_at: string; quality: string };
type Anomaly = { type: string; direction?: string; periods: string[]; supporting_observations: Observation[]; why: string };
type Series = { series: string; status: string; persistent: boolean; latest_period: string | null; direction: string | null; momentum: string | null; acceleration: string | null; anomalies: Anomaly[]; limitations: string[] };
type Relationship = { key: string; status: string; question: string; observations: Observation[]; competing_explanations: string[]; limitations: string; hypothesis: { proposed_reinforcing_mechanism: string; potential_balancing_mechanism: string; confirmation_needed: string[]; falsification_conditions: string[]; implications_1_3_months: string; implications_3_6_months: string } };
type Discovery = { as_of: string; knowledge_mode: string; analysis_basis: string; rule_version: string; persistent_anomalies: Series[]; relationships: Relationship[]; series: Record<string, Series>; limitations: string; source_coverage: { numeric_series: number; unavailable_relationships: string[] }; investigations: { id: number; candidate_key: string; status: string; updated_at: string }[] };

async function investigate(form: FormData) {
  'use server';
  const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const token = String(form.get('operator_token') || '');
  const headers = { 'Content-Type': 'application/json', 'X-Admin-Token': token };
  const snapshot = await fetch(`${api}/api/v1/research/discovery/snapshots`, { method: 'POST', headers, body: JSON.stringify({ snapshot_key: String(form.get('snapshot_key')), as_of: String(form.get('as_of')), knowledge_mode: String(form.get('knowledge_mode')) }), cache: 'no-store' });
  if (!snapshot.ok) throw new Error(`Could not freeze discovery evidence (${snapshot.status}). Check research:write scope.`);
  const frozen = await snapshot.json();
  const response = await fetch(`${api}/api/v1/research/discovery/hypotheses`, { method: 'POST', headers, body: JSON.stringify({ snapshot_id: frozen.id, candidate_key: String(form.get('candidate_key')), investigation_question: String(form.get('question')) }), cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not open hypothesis (${response.status}). Refresh the candidate and retry.`);
}

function Evidence({ items }: { items: Observation[] }) {
  return <ul>{items.map(o => <li key={`${o.kind}-${o.id}`}>#{o.id} {o.series}: {o.value} ({o.period_end}, {o.quality}, revision {o.revision}) · <a href={o.source_reference} target="_blank" rel="noreferrer">{o.source}</a> · published {o.published_at || 'unknown'} · retrieved {o.retrieved_at}</li>)}</ul>;
}

export default async function DiscoveryPage({ searchParams }: { searchParams: Promise<{ as_of?: string; knowledge_mode?: string }> }) {
  const params = await searchParams;
  const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const token = process.env.RESEARCH_OPERATOR_TOKEN;
  let data: Discovery | null = null;
  if (token) {
    const query = new URLSearchParams();
    if (params.as_of) query.set('as_of', params.as_of);
    query.set('knowledge_mode', params.knowledge_mode === 'source_known' ? 'source_known' : 'system_known');
    const response = await fetch(`${api}/api/v1/research/discovery?${query}`, { headers: { 'X-Admin-Token': token }, cache: 'no-store' }).catch(() => null);
    if (response?.ok) data = await response.json();
  }
  const inflectionSignals = data?.persistent_anomalies.flatMap(s => s.anomalies.filter(a => a.type !== 'sustained_deviation').map(a => ({ series: s.series, anomaly: a }))) || [];
  return <main className="container">
    <header className="header"><div><div className="eyebrow">SMART HEDGE / PRIVATE RESEARCH</div><h1>Persistent anomaly discovery</h1><p className="subtitle">Observed pattern → possible mechanism → competing explanations → investigation</p><Link href="/intelligence">← Cycle intelligence</Link></div><div className="header-right"><strong className="live-label">PROVISIONAL RESEARCH</strong><span>{data?.as_of || 'Unavailable'}</span></div></header>
    {!data ? <section className="panel"><h2>Discovery unavailable</h2><p>Private access, source data, or the research API is unavailable. No synthetic observations are substituted.</p></section> : <>
      <p className="caption">{data.analysis_basis} · {data.rule_version} · {data.source_coverage.numeric_series} numeric series. {data.limitations}</p>
      <div className="section-heading"><div><div className="eyebrow">NEW AND PERSISTENT</div><h2>Observed anomalies</h2></div></div>
      {data.persistent_anomalies.length ? data.persistent_anomalies.map(s => <details className="panel" key={s.series}><summary><strong>{s.series} · {s.status}</strong></summary><p>Latest {s.latest_period}. Direction {s.direction}; momentum {s.momentum}; acceleration {s.acceleration}.</p>{s.anomalies.map(a => <div key={a.type}><h3>{a.type.replaceAll('_', ' ')}</h3><p>{a.why}</p><Evidence items={a.supporting_observations}/></div>)}{s.limitations.map(l => <p key={l}>{l}</p>)}</details>) : <section className="panel"><p>No persistent anomaly supported by available numeric series. Isolated movements are not promoted.</p></section>}
      <div className="section-heading"><div><div className="eyebrow">WHAT MIGHT BE CHANGING?</div><h2>Potential inflection signals</h2></div></div>
      {inflectionSignals.length ? inflectionSignals.map(({ series, anomaly }) => <p className="panel" key={`${series}-${anomaly.type}`}>{series}: {anomaly.type.replaceAll('_', ' ')} across {anomaly.periods.join(', ')}. {anomaly.why} Statistical signal only; no cycle transition is inferred.</p>) : <section className="panel"><p>No persistent directional or structural-change signal is supported.</p></section>}
      <div className="section-heading"><div><div className="eyebrow">UNEXPLAINED RELATIONSHIPS</div><h2>Candidate mechanism inbox</h2></div></div>
      {data.relationships.length ? data.relationships.map(r => <details className="panel" key={r.key}><summary><strong>{r.question}</strong></summary><p>{r.limitations}</p><p>Proposed mechanism: {r.hypothesis.proposed_reinforcing_mechanism}</p><p>Possible balancing force: {r.hypothesis.potential_balancing_mechanism}</p><p>Competing explanations: {r.competing_explanations.join('; ')}</p><p>Confirm with: {r.hypothesis.confirmation_needed.join('; ')}</p><p>Falsify with: {r.hypothesis.falsification_conditions.join('; ')}</p><p>1–3 months: {r.hypothesis.implications_1_3_months}</p><p>3–6 months: {r.hypothesis.implications_3_6_months}</p><Evidence items={r.observations}/><form action={investigate}><input type="hidden" name="candidate_key" value={r.key}/><input type="hidden" name="snapshot_key" value={`discovery-${data.knowledge_mode}-${data.as_of}-${r.key}`.slice(0, 160)}/><input type="hidden" name="as_of" value={data.as_of}/><input type="hidden" name="knowledge_mode" value={data.knowledge_mode}/><input type="hidden" name="question" value={r.question}/><label>Operator token <input type="password" name="operator_token" required autoComplete="off" /></label><button type="submit">Freeze evidence and investigate</button></form></details>) : <section className="panel"><p>No cross-indicator candidate passes persistence, freshness and configured economic relevance checks. Missing pair coverage: {data.source_coverage.unavailable_relationships.join(', ') || 'none'}.</p></section>}
      {data.investigations.length > 0 && <section className="panel"><h2>Investigation updates</h2>{data.investigations.map(item => <p key={item.id}>#{item.id} · {item.status} · updated {item.updated_at} · {item.candidate_key}</p>)}</section>}
      <section className="panel"><h2>Retrospective research</h2><p>Use a dated as-of timestamp and choose system-known for what SmartHedge had ingested then, or source-known for a reconstruction using independently dated releases. Source-known is not a live historical assessment.</p><form method="get"><label>As of (ISO 8601 with timezone) <input name="as_of" placeholder="2025-12-31T18:00:00+00:00" defaultValue={params.as_of || ''}/></label><label>Knowledge mode <select name="knowledge_mode" defaultValue={data.knowledge_mode}><option value="system_known">System known</option><option value="source_known">Source known retrospective</option></select></label><button type="submit">Inspect episode</button></form></section>
      <section className="panel"><h2>Other observed series</h2>{Object.values(data.series).filter(s => !s.persistent).map(s => <p key={s.series}>{s.series}: {s.status} · {s.latest_period || 'no period'} · {s.limitations.join('; ')}</p>)}</section>
    </>}
  </main>;
}
