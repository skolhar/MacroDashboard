type Evidence = { indicator_id: string; observed: number | null; required: number | null; result: boolean | null; status?: string; published_at?: string | null; provider?: string | null };
type Alert = { id: string; rule_id: string; label?: string; status: string; persistence_count: number; recovery_count?: number; evidence: Evidence[]; confidence?: string; invalidation_condition?: string };
type Metric = { id: string; display_name: string; cycle: string; value: number | null; unit: string; status: string; period_start: string | null; period_end: string | null; published_at: string | null; ingested_at: string | null; provider: string | null; quality: string | null; feature: number | null; transform: string; vintage_id: string | null; source_url?: string | null };
type Cycle = { id: string; score: number | null; weight: number; coverage: number; status: string; direction?: string; momentum?: number | null; acceleration?: number | null; history?: { as_of: string; score: number | null }[]; confidence?: string; reason?: string | null; confirmation?: { stressed_signals: number; available_signals: number }; contributors: { indicator_id: string; score: number | null; weight: number }[] };
type Dashboard = { as_of: string; mode: string; environment?: string; ruleset_version: string; overall: { score: number | null; regime: string; coverage: number; prior_regime?: string; reason?: string | null }; data_confidence?: { score: number | null; coverage_percent?: number; source_backed_count?: number; registered_count?: number; reason?: string }; cycles: Cycle[]; alerts: Alert[]; metrics: Metric[]; source_health: { stale_count: number; unavailable_count: number; calendar_unverified_count?: number; last_successful_ingestion?: string | null }; warnings: string[] };
type Series = { items: { period_end: string; value: number; provider?: string; published_at?: string }[] };
type History = { items: { id: number; rule_id: string; status: string; evaluated_at: string; ruleset_version: string }[] };

const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
const labels: Record<string, string> = { fx: 'FX / External', energy: 'Oil / Rates', flows: 'Flows / SIP', earnings: 'Earnings / Valuation', it: 'IT / AI', global: 'Global' };
const fmt = (n: number | null | undefined, digits = 1) => n == null ? 'N/A' : n.toLocaleString('en-IN', { maximumFractionDigits: digits });
async function getJson<T>(path: string): Promise<T> { const response = await fetch(`${api}${path}`, { cache: 'no-store' }); if (!response.ok) throw new Error(`API ${response.status}`); return response.json(); }

function chartData(rows: Series['items'], transform: string) {
  const n = Number(transform.split('_').at(-1));
  if (!Number.isFinite(n) || n < 1 || (!transform.startsWith('change_pct_') && !transform.startsWith('change_bps_'))) return rows.map(r => ({ ...r, plotted: r.value }));
  return rows.map((r, i) => {
    const previous = rows[i - n]?.value;
    const plotted = previous == null || (transform.startsWith('change_pct_') && previous <= 0) ? null : transform.startsWith('change_bps_') ? 100 * (r.value - previous) : 100 * (r.value / previous - 1);
    return { ...r, plotted };
  }).filter(r => r.plotted !== null);
}

function Chart({ rows, metric, thresholds }: { rows: Series['items']; metric: Metric; thresholds?: { amber: number; red: number } }) {
  const data = chartData(rows, metric.transform);
  if (data.length < 2) return <div className="empty">DATA UNAVAILABLE · insufficient history</div>;
  const values = data.map(r => r.plotted as number);
  const compatible = metric.transform === 'raw' || metric.transform.startsWith('change_pct_') || metric.transform.startsWith('change_bps_');
  const thresholdValues = compatible && thresholds ? [thresholds.amber, thresholds.red] : [];
  const min = Math.min(...values, ...thresholdValues); const max = Math.max(...values, ...thresholdValues); const span = max - min || 1;
  const x = (i: number) => i / (data.length - 1) * 100;
  const y = (v: number) => 90 - (v - min) / span * 70;
  const points = values.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(' ');
  return <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${metric.display_name} ${metric.transform} chart with source dates and threshold lines`}>
    {[20, 55, 90].map(at => <line key={at} x1="0" y1={at} x2="100" y2={at} stroke="#324057" strokeWidth=".4"/>)}
    {thresholdValues.map((v, i) => <line key={i} x1="0" y1={y(v)} x2="100" y2={y(v)} stroke={i ? '#d27c75' : '#d7b16d'} strokeWidth=".8" strokeDasharray="3 2" vectorEffect="non-scaling-stroke"/>)}
    <polyline fill="none" stroke="#63d7d0" strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={points}/>
    {data.map((r, i) => <circle key={`${r.period_end}-${i}`} cx={x(i)} cy={y(r.plotted as number)} r=".55" fill="#9ce8e1"><title>{`${r.period_end}: ${fmt(r.plotted, 2)} · ${r.provider || 'source unknown'} · published ${r.published_at || 'unknown'}`}</title></circle>)}
  </svg><div className="chart-axis"><span>{data[0].period_end}</span><span>{metric.transform} · {metric.unit}</span><span>{data.at(-1)?.period_end}</span></div></div>;
}


/**
 * Existing cycle scores measure macro stress, NOT the direction of an asset price.
 * Until a point-in-time validated instrument mapping exists, report the trend as
 * unavailable and expose the relevant cycle context without inventing signals.
 */
function MarketTrendStrip({ data }: { data: Dashboard }) {
  const instruments = [
    { name: 'Nifty 50', context: ['earnings', 'flows', 'global'] },
    { name: 'MCX Crude Oil', context: ['energy', 'global'] },
    { name: 'USD/INR', context: ['fx', 'global'] },
  ];
  return <section className="panel" aria-label="Instrument trend overview" style={{ marginBottom: '1rem' }}>
    <div className="panel-heading"><div><div className="eyebrow">MODEL / INSTRUMENT OUTLOOK</div><h2>Nifty · Crude · USD/INR</h2></div><span className="muted">Directional mapping not yet validated</span></div>
    <div className="cycle-grid">
      {instruments.map(item => {
        const cycles = item.context.map(id => data.cycles.find(c => c.id === id)).filter((c): c is Cycle => Boolean(c));
        const usable = cycles.filter(c => c.score !== null && c.coverage > 0);
        return <article className="cycle-card" key={item.name}>
          <h3>{item.name}</h3>
          <div className="cycle-score">N/A</div>
          <p className="muted">Trend unavailable · no validated asset-direction model</p>
          <p className="caption">Macro context: {usable.length ? usable.map(c => `${labels[c.id] || c.id}: ${fmt(c.score)} stress (${Math.round(c.coverage * 100)}% coverage)`).join(' · ') : 'Insufficient source-backed cycle coverage'}</p>
          <small className="muted">{item.name === 'USD/INR' ? 'Monitoring only · no currency trading signal' : 'No trade direction implied'} · {data.mode === 'demo' ? 'Synthetic demonstration' : 'Source and model gates apply'}</small>
        </article>;
      })}
    </div>
  </section>;
}

export default async function Monitor({ searchParams }: { searchParams: Promise<{ as_of?: string; metric?: string; ruleset?: string }> }) {
  const params = await searchParams;
  const query = new URLSearchParams();
  if (params.as_of) query.set('as_of', params.as_of);
  if (params.ruleset) query.set('ruleset', params.ruleset);
  let data: Dashboard;
  try { data = await getJson<Dashboard>(`/api/v1/dashboard?${query}`); }
  catch { return <main className="container"><h1>SmartHedge monitor</h1><p>DATA UNAVAILABLE · the API is not responding. Check the service health before interpreting any score.</p></main>; }
  const metric = data.metrics.find(m => m.id === params.metric) || data.metrics[0];
  const seriesQuery = new URLSearchParams(); if (params.as_of) seriesQuery.set('as_of', params.as_of);
  const [series, history] = await Promise.all([
    getJson<Series>(`/api/v1/indicators/${metric.id}/series?${seriesQuery}`).catch(() => ({ items: [] })),
    getJson<History>('/api/v1/alerts/history').catch(() => ({ items: [] }))
  ]);
  const threshold = data.cycles.flatMap(c => c.contributors).find(c => c.indicator_id === metric.id) as (Cycle['contributors'][number] & { thresholds?: { amber: number; red: number } }) | undefined;
  const active = data.alerts.filter(a => ['WATCH', 'TRIGGERED', 'CONFIRMED', 'WARNING', 'CRITICAL'].includes(a.status));
  const sourcesNeedingAttention = data.metrics.filter(m => ['stale', 'DATA_UNAVAILABLE', 'CALENDAR_UNVERIFIED', 'unavailable', 'provisional', 'estimated', 'source_conflict'].includes(m.status));
  const demo = data.mode === 'demo';
  return <main className="container">
    <header className="header"><div><div className="eyebrow">SMART HEDGE / INDIA MACRO RESEARCH</div><h1>Inflection Monitor</h1><p className="subtitle">Financial flows · fundamentals · expectations · policy response</p><a href="/external-liquidity">India External Liquidity →</a></div><div className="header-right"><strong className={demo ? 'demo' : 'live-label'}>{demo ? 'DEMO · SYNTHETIC DATA' : data.environment === 'staging' ? 'STAGING · SOURCE-BACKED DATA ONLY' : 'LIVE MODE · VERIFIED INPUTS ONLY'}</strong><span>As of {new Date(data.as_of).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })} IST</span><span>Ruleset {data.ruleset_version} · provisional thresholds</span></div></header>
    <MarketTrendStrip data={data}/>
    <form className="filters" action="/" method="get" aria-label="Dashboard filters"><label>As-of timestamp (ISO + timezone) <input type="text" name="as_of" placeholder="2026-10-31T00:00:00+05:30" defaultValue={params.as_of || ''} /></label><label>Ruleset <select name="ruleset" defaultValue={params.ruleset || data.ruleset_version}><option value="v1">v1 Phase 1</option><option value="v2">v2 experimental</option></select></label><label>Indicator <select name="metric" defaultValue={metric.id}>{data.metrics.map(m => <option key={m.id} value={m.id}>{m.display_name}</option>)}</select></label><button type="submit">Apply</button></form>
    <section className="summary" aria-label="Overall risk summary"><div><div className="eyebrow">COMPOSITE REFLEXIVITY RISK</div><div className="score">{fmt(data.overall.score)}<small>{data.overall.score === null ? '' : ' / 100'}</small></div><p>{data.overall.regime === 'insufficient_data' ? 'Insufficient cycle coverage' : data.overall.regime}</p>{data.overall.prior_regime && <small className="muted">Prior regime: {data.overall.prior_regime}</small>}</div><div className="summary-stat"><span>Score coverage</span><strong>{Math.round(data.overall.coverage * 100)}%</strong><small>Configured weights retained</small></div><div className="summary-stat"><span>Data confidence</span><strong>{fmt(data.data_confidence?.score)}{data.data_confidence?.score == null ? '' : ' / 100'}</strong><small>Operational coverage/quality index · not statistical certainty</small><small>{data.data_confidence?.source_backed_count ?? 0}/{data.data_confidence?.registered_count ?? data.metrics.length} source-backed</small></div><div className="summary-stat"><span>Inflection alerts</span><strong>{active.length} active</strong><small>{data.alerts.length} rules evaluated</small></div><div className="summary-note">{data.overall.reason || (demo ? 'Synthetic test inputs are never mixed with live scores.' : 'Risk index only; not a probability or trade signal.')}</div></section>
    <div className="section-heading"><div><div className="eyebrow">SIX MONITORED CYCLES</div><h2>Stress overview</h2></div><span className="muted">Level · momentum · acceleration · coverage</span></div>
    <section className="cycle-grid" aria-label="Six cycle panels">{data.cycles.map((cycle, i) => <article className="cycle-card" key={cycle.id}><div className="cycle-top"><span className="cycle-number">0{i + 1}</span><span className={`pill ${cycle.score === null ? 'neutral' : cycle.score >= 65 ? 'high' : cycle.score >= 45 ? 'watch' : 'low'}`}>{cycle.status}</span></div><h3>{labels[cycle.id]}</h3><div className="cycle-score">{fmt(cycle.score)}<small>{cycle.score == null ? '' : ' / 100'}</small></div><div className="bar" aria-label={`${Math.round(cycle.coverage * 100)} percent coverage`}><i style={{ width: `${cycle.coverage * 100}%` }} /></div><div className="cycle-meta"><span>{Math.round(cycle.coverage * 100)}% coverage</span><span>{cycle.weight}% weight</span></div><div className="cycle-detail"><div><span>Momentum</span><b>{fmt(cycle.momentum)}</b></div><div><span>Acceleration</span><b>{fmt(cycle.acceleration)}</b></div><div><span>Confirmation</span><b>{cycle.confirmation ? `${cycle.confirmation.stressed_signals}/${cycle.confirmation.available_signals}` : 'N/A'}</b></div><div><span>Confidence</span><b>{cycle.confidence || 'unknown'}</b></div></div>{cycle.history && <p className="cycle-history">56d / 28d / now: {cycle.history.map(point => fmt(point.score)).join(" / ")}</p>}</article>)}</section>
    <div className="lower-grid"><section className="panel"><div className="panel-heading"><div><div className="eyebrow">INDICATOR EXPLORER</div><h2>{metric.display_name}</h2></div><span className="pill neutral">{metric.status}</span></div><Chart rows={series.items} metric={metric} thresholds={threshold?.thresholds}/><p className="caption">Latest level {fmt(metric.value, 2)} {metric.unit} · feature {metric.transform}: {fmt(metric.feature, 2)}. Amber and red dashed lines appear only when the plotted transform matches the rule threshold. Chart values show date and source on hover.</p></section><section className="panel"><div className="panel-heading"><div><div className="eyebrow">REFLEXIVE INFLECTIONS</div><h2>Active alerts</h2></div><span className="pill neutral">{active.length} active</span></div>{active.length ? active.map(alert => <details className="alert-card" key={alert.id} open><summary><strong>{alert.label || alert.rule_id.replaceAll('_', ' ')}</strong><span className="pill watch">{alert.status}</span></summary><p className="muted">{alert.persistence_count} qualifying evaluations · {alert.confidence || 'provisional'} confidence</p><div className="alert-evidence">{alert.evidence.map(e => <div key={e.indicator_id}><span>{data.metrics.find(m => m.id === e.indicator_id)?.display_name || e.indicator_id}</span><b>{e.result === null ? 'Unknown' : e.result ? `Met · ${fmt(e.observed, 2)}` : `Counter · ${fmt(e.observed, 2)}`}</b></div>)}</div><p className="caption">Invalidation: {alert.invalidation_condition || 'Conditions must stay below recovery threshold.'}</p></details>) : <p className="muted">No confirmed active inflection. Missing evidence may leave rules UNKNOWN.</p>}<div className="alert-history"><strong>Recent transitions</strong>{history.items.length ? history.items.slice(0, 6).map(h => <div key={h.id}>{h.rule_id.replaceAll('_', ' ')} · {h.status} · {new Date(h.evaluated_at).toLocaleDateString('en-IN')}</div>) : <p className="muted">No stored transitions yet.</p>}</div></section></div>
    <section className="panel health-panel"><div className="panel-heading"><div><div className="eyebrow">SOURCE HEALTH</div><h2>Coverage and freshness</h2><small className="muted">Last successful ingestion: {data.source_health.last_successful_ingestion ? new Date(data.source_health.last_successful_ingestion).toLocaleString('en-IN') : 'None'}</small></div><span className="muted">{data.source_health.stale_count} stale · {data.source_health.unavailable_count} unavailable</span></div><div className="health-list">{sourcesNeedingAttention.length ? sourcesNeedingAttention.map(m => <div key={m.id}><b>{m.display_name}</b><span>{m.status}</span><small>{m.period_end ? `Last observation ${m.period_end}` : 'No eligible observation'}</small></div>) : <p>All configured inputs have an eligible observation at this as-of time.</p>}</div></section>
    <section className="panel metrics"><div className="panel-heading"><div><div className="eyebrow">SOURCE PROVENANCE</div><h2>{demo && data.metrics.length === 12 ? '12 core indicators' : `${data.metrics.length} registered indicators`}</h2></div><span className="muted">Select a row for publication and vintage details</span></div><div className="metric-grid">{data.metrics.map(m => <details className="metric" key={m.id}><summary><span><b>{m.display_name}</b><small>{labels[m.cycle]}</small></span><span className="metric-value">{fmt(m.value, 2)}<small>{m.unit}</small></span><span className={`status ${m.status}`}>{m.status.toUpperCase()}</span></summary><div className="provenance"><div>Observation: {m.period_start || 'Unavailable'} to {m.period_end || 'Unavailable'}</div><div>Published: {m.published_at || 'Unavailable'}</div><div>Ingested: {m.ingested_at || 'Unavailable'}</div><div>Provider: {m.provider || 'Unavailable'}</div><div>Quality: {m.quality || 'Unavailable'}</div><div>Vintage: {m.vintage_id || 'Unavailable'}</div><div>Feature: {m.transform} = {fmt(m.feature, 2)}</div>{m.source_url && <div>Source: <a href={m.source_url} rel="noreferrer" target="_blank">Original reference</a></div>}<div>Thresholds: provisional; not historically validated</div></div></details>)}</div></section>
    <footer><strong>{demo ? 'DEMO · SYNTHETIC DATA' : 'LIVE MODE · SOURCE-CHECKED DATA ONLY'}</strong><span>Market research. Not investment advice or a crash forecast.</span><a href={process.env.API_DOCS_URL || 'http://localhost:8000/docs'}>API documentation</a></footer>
  </main>;
}
