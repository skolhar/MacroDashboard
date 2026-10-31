import './external.css';
type Metric = { id: string; display_name: string; value: number | null; feature: number | null; unit: string; status: string; provider: string | null; period_end: string | null; published_at: string | null; source_url: string | null; quality: string | null };
type View = { as_of: string; mode: string; environment: string; cycle: { score: number | null; coverage: number; confidence: string }; data_confidence: { score: number | null; reason: string } | null; source_health: { last_successful_ingestion: string | null }; classification: string; explanation: string; expectations_evidence: string; forward_interpretation: string; signals: Record<string, boolean | null>; metrics: Metric[]; alert: { status: string; evidence: { indicator_id: string; result: boolean | null; observed: number | null }[]; invalidation_condition?: string } | null; warning: string };
type Series = { items: { period_end: string; value: number; quality: string; provider: string; published_at: string }[] };
const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
const fmt = (n: number | null | undefined, digits = 1) => n == null ? 'N/A' : n.toLocaleString('en-IN', { maximumFractionDigits: digits });
const sections = [
  { id: 'usd_inr_spot', label: 'USD/INR exchange rate', note: 'RBI observations are economic reference rates; licensed spot quotes are separately sourced. Never treat a reference fixing as a live tradable quote.' },
  { id: 'fx_gross_reserves_usd', label: 'Gross FX reserves', note: 'Valuation changes may affect reported reserves.' },
  { id: 'rbi_net_forward_usd', label: 'RBI forward position', note: 'Context only until sign and maturity definitions are validated.' },
  { id: 'fpi_equity_net_inr', label: 'FPI equity flows', note: 'Provisional trade and settled custody data must be distinguished.' },
  { id: 'fpi_debt_net_inr', label: 'FPI debt flows', note: 'Confirm reporting basis before comparison.' },
  { id: 'india_10y_yield', label: 'India 10Y G-Sec yield', note: 'Yield level in percent; changes in basis points.' },
  { id: 'brent_usd', label: 'Brent crude', note: 'Licensed commodity feed required.' },
  { id: 'sip_contribution_inr', label: 'AMFI SIP contributions', note: 'Monthly domestic liquidity context.' },
  { id: 'midcap_mf_net_inr', label: 'Mid-cap fund flows', note: 'Monthly domestic liquidity context.' },
  { id: 'smallcap_mf_net_inr', label: 'Small-cap fund flows', note: 'Monthly domestic liquidity context.' },
];

function Sparkline({ rows, name }: { rows: Series['items']; name: string }) {
  const trusted = rows.filter(r => ['verified', 'revised', 'demo'].includes(r.quality));
  if (trusted.length < 2) return <div className="empty">DATA UNAVAILABLE · at least two eligible observations required</div>;
  const values = trusted.map(r => r.value), lo = Math.min(...values), hi = Math.max(...values), spread = hi - lo || 1;
  const points = trusted.map((r, i) => `${(i * 100 / (trusted.length - 1)).toFixed(2)},${(85 - (r.value - lo) / spread * 65).toFixed(2)}`).join(' ');
  return <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${name} source-backed historical levels`}><polyline fill="none" stroke="#63d7d0" strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={points}/>{trusted.map((r, i) => <circle key={`${r.period_end}-${i}`} cx={i * 100 / (trusted.length - 1)} cy={85 - (r.value - lo) / spread * 65} r=".7" fill="#9ce8e1"><title>{`${r.period_end}: ${fmt(r.value, 3)} · ${r.provider} · published ${r.published_at}`}</title></circle>)}</svg><div className="chart-axis"><span>{trusted[0].period_end}</span><span>Reported level</span><span>{trusted.at(-1)?.period_end}</span></div></div>;
}

export default async function ExternalLiquidity({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const params = await searchParams;
  const query = new URLSearchParams(); if (params.as_of) query.set('as_of', params.as_of);
  let data: View;
  try { const response = await fetch(`${api}/api/v1/external-liquidity?${query}`, { cache: 'no-store' }); if (!response.ok) throw Error(); data = await response.json(); }
  catch { return <main className="container"><h1>India External Liquidity</h1><p>DATA UNAVAILABLE · source service is unavailable.</p></main>; }
  const series = await Promise.all(sections.map(async section => {
    try { const r = await fetch(`${api}/api/v1/indicators/${section.id}/series?${query}`, { cache: 'no-store' }); return r.ok ? await r.json() as Series : { items: [] }; }
    catch { return { items: [] }; }
  }));
  const demo = data.mode === 'demo';
  return <main className="container external-monitor">
    <header className="header"><div><div className="eyebrow">SMART HEDGE / INDIA MACRO RESEARCH</div><h1>India External Liquidity</h1><p className="subtitle">Currency · foreign flows · reserves · oil · rates</p><a href="/">← Inflection Monitor</a></div><div className="header-right"><strong className={demo ? 'demo' : 'live-label'}>{demo ? 'DEMO · SYNTHETIC DATA' : data.environment === 'staging' ? 'STAGING · SOURCE-BACKED DATA ONLY' : 'LIVE MODE · VERIFIED INPUTS ONLY'}</strong><span>As of {new Date(data.as_of).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })} IST</span><span>v2 provisional thresholds</span></div></header>
    <form className="filters" action="/external-liquidity" method="get"><label>As-of timestamp <input name="as_of" type="text" defaultValue={params.as_of || ''} placeholder="2026-10-31T00:00:00+05:30" /></label><button type="submit">Apply</button></form>
    <section className="summary" aria-label="External liquidity summary"><div><div className="eyebrow">EXTERNAL-LIQUIDITY CYCLE RISK</div><div className="score">{fmt(data.cycle.score)}<small>{data.cycle.score == null ? '' : ' / 100'}</small></div><p>Risk index, not a crash probability</p></div><div className="summary-stat"><span>Cycle coverage</span><strong>{Math.round(data.cycle.coverage * 100)}%</strong><small>{data.cycle.confidence}</small></div><div className="summary-stat"><span>Data confidence</span><strong>{fmt(data.data_confidence?.score)}</strong><small>Operational coverage/quality index; not statistical certainty</small></div><div className="summary-stat"><span>Last ingestion</span><strong className="external-date">{data.source_health.last_successful_ingestion ? new Date(data.source_health.last_successful_ingestion).toLocaleDateString('en-IN') : 'None'}</strong></div></section>
    <section className="panel"><div className="eyebrow">FEEDBACK-LOOP ASSESSMENT</div><h2>{data.classification.replaceAll('_', ' ')}</h2><p>{data.explanation}</p><p className="muted">{data.expectations_evidence}</p><p className="muted">{data.forward_interpretation}</p><div className="external-signals">{Object.entries(data.signals).map(([key, value]) => <span className="pill neutral" key={key}>{key.replaceAll('_', ' ')}: {value === null ? 'UNKNOWN' : value ? 'MET' : 'NOT MET'}</span>)}</div><p className="caption">{data.warning}</p></section>
    <div className="section-heading"><div><div className="eyebrow">SOURCE-BACKED HISTORY</div><h2>Indicator levels and provenance</h2></div><span className="muted">Charts appear only when observations exist</span></div>
    <div className="external-grid">{sections.map((section, i) => { const metric = data.metrics.find(m => m.id === section.id); return <section className="panel" key={section.id}><div className="panel-heading"><div><div className="eyebrow">{metric?.status || 'DATA_UNAVAILABLE'}</div><h2>{section.label}</h2></div><strong>{fmt(metric?.value, 2)} {metric?.value == null ? '' : metric?.unit}</strong></div><Sparkline rows={series[i].items} name={section.label}/><p className="caption">{section.note} {metric?.provider ? `Source: ${metric.provider}.` : 'No source-backed observation.'} {metric?.published_at ? `Published: ${metric.published_at}.` : ''} {metric?.source_url && <a href={metric.source_url} rel="noreferrer" target="_blank">Original reference</a>}</p></section>; })}</div>
    <section className="panel"><div className="eyebrow">RUPEE STRESS ALERT</div><h2>{data.alert?.status || 'UNKNOWN'}</h2><p>Trigger evidence: depreciation, foreign selling, elevated oil and lower gross reserves. Missing publications remain unknown.</p>{data.alert?.evidence?.map(e => <p key={e.indicator_id}>{e.indicator_id}: {e.result === null ? 'UNKNOWN' : e.result ? 'MET' : 'COUNTER'} · {fmt(e.observed)}</p>)}<p className="caption">Invalidation: {data.alert?.invalidation_condition || 'Require sustained recovery in the configured rule; missing observations do not imply recovery.'}</p></section>
    <footer><span>{demo ? 'DEMO · SYNTHETIC DATA' : 'STAGING / SOURCE-CHECKED DATA ONLY'}</span><span>Exploratory macro research. No investment or trading signal.</span></footer>
  </main>;
}
