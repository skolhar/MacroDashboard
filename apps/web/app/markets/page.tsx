import '../external-liquidity/external.css';
import './market.css';

type Status = { status: string; reason?: string; last_session_date?: string | null; last_retrieved_at?: string | null; age_calendar_days?: number | null; last_fetch_status?: string; last_error_code?: string | null; last_rejected_rows?: number | null; quality?: string | null; bar_count?: number; possible_weekday_gaps_last_60?: string[]; gap_caveat?: string };
type Instrument = { id: string; name: string; kind: string; market: string; currency: string; timezone: string; provider_symbol: string; status: Status };
type History = { instrument_id: string; basis: string; items: { session_date: string; open: number | null; high: number | null; low: number | null; close: number | null; raw_open: number; raw_high: number; raw_low: number; raw_close: number; adjusted_close: number | null; volume: number | null; retrieved_at: string; source_url: string; quality: string; contract_identity: string | null; roll_policy: string | null }[]; status: Status };
const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
const format = (value: number | null | undefined) => value == null ? 'N/A' : value.toLocaleString('en-IN', { maximumFractionDigits: 3 });

function PriceChart({ rows, name }: { rows: History['items']; name: string }) {
  const valid = rows.filter((row): row is typeof row & { close: number } => row.close !== null);
  if (valid.length < 2) return <div className="empty">DATA UNAVAILABLE · two source-backed daily closes required</div>;
  const latest = valid.slice(-180), prices = latest.map(row => row.close), lo = Math.min(...prices), spread = Math.max(...prices) - lo || 1;
  const points = latest.map((row, i) => `${(i * 100 / (latest.length - 1)).toFixed(2)},${(85 - (row.close - lo) / spread * 65).toFixed(2)}`).join(' ');
  return <div className="chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${name} Yahoo daily closing-price history`}><polyline fill="none" stroke="#63d7d0" strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={points}/></svg><div className="chart-axis"><span>{latest[0].session_date}</span><span>Daily close · {latest.length} bars</span><span>{latest.at(-1)?.session_date}</span></div></div>;
}

export default async function Markets({ searchParams }: { searchParams: Promise<{ instrument?: string; basis?: string; as_of?: string }> }) {
  const params = await searchParams;
  let catalog: { mode: string; provider: string; items: Instrument[] };
  try { const response = await fetch(`${api}/api/v1/market/instruments`, { cache: 'no-store' }); if (!response.ok) throw Error(); catalog = await response.json(); }
  catch { return <main className="container"><h1>Market Research</h1><p>DATA UNAVAILABLE · market-data service is unavailable.</p></main>; }
  const selected = catalog.items.find(item => item.id === params.instrument) || catalog.items[0];
  const basis = params.basis === 'adjusted_close' ? 'adjusted_close' : 'raw';
  let history: History = { instrument_id: selected?.id || '', basis, items: [], status: { status: 'DATA_UNAVAILABLE' } };
  if (selected) {
    const query = new URLSearchParams({ basis, limit: '1000' }); if (params.as_of) query.set('as_of', params.as_of);
    try { const response = await fetch(`${api}/api/v1/market/instruments/${selected.id}/history?${query}`, { cache: 'no-store' }); if (response.ok) history = await response.json(); }
    catch { /* unavailable remains explicit */ }
  }
  const last = history.items.at(-1);
  return <main className="container external-monitor market-monitor">
    <header className="header"><div><div className="eyebrow">SMARTHEDGE / MACRO INVESTMENT INTELLIGENCE</div><h1>Market Research</h1><p className="subtitle">Daily underlying and ETF prices · source status · historical context</p><a href="/">← Inflection Monitor</a></div><div className="header-right"><strong className={catalog.mode === 'isolated_research' ? 'live-label' : 'demo'}>{catalog.mode === 'isolated_research' ? `ISOLATED RESEARCH · ${catalog.provider.toUpperCase()} SECONDARY DATA` : 'DATA UNAVAILABLE · RESEARCH FEED DISABLED'}</strong><span>Price history only · no market-direction model</span></div></header>
    <section className="panel"><div className="eyebrow">SOURCE AND RIGHTS</div><p>Yahoo/yfinance daily history is a secondary research source. Raw OHLC and adjusted close are separate. This view is disabled for public production display until storage and redistribution rights are reviewed. No synthetic price substitutes, brokerage connection or trading execution.</p><p className="caption">WTI, Brent and gold are global continuous futures proxies with an unverified vendor roll policy. WTI is not MCX crude. Yahoo USD/INR is not an RBI/FBIL published reference fixing.</p></section>
    <div className="market-layout"><section className="panel"><div className="eyebrow">INSTRUMENTS</div><div className="market-list">{catalog.items.map(item => <a className={item.id === selected?.id ? 'market-choice active' : 'market-choice'} key={item.id} href={`/markets?instrument=${encodeURIComponent(item.id)}&basis=${basis}`}><strong>{item.name}</strong><span>{item.provider_symbol} · {item.currency} · {item.status.status}</span></a>)}</div></section>
    <section className="panel"><div className="eyebrow">{selected?.kind.toUpperCase() || 'DATA UNAVAILABLE'} / {selected?.market || 'UNKNOWN'}</div><h2>{selected?.name || 'No instrument selected'}</h2><p>{selected?.provider_symbol} · latest raw close {format(last?.raw_close)} {selected?.currency} · session {last?.session_date || 'N/A'}</p><form className="filters" action="/markets" method="get"><input type="hidden" name="instrument" value={selected?.id || ''}/><label>Price basis <select name="basis" defaultValue={basis}><option value="raw">Raw OHLC</option><option value="adjusted_close">Adjusted close only</option></select></label><label>As of <input name="as_of" defaultValue={params.as_of || ''} placeholder="ISO timestamp with timezone"/></label><button type="submit">Apply</button></form><PriceChart rows={history.items} name={selected?.name || 'Instrument'}/><p className="caption">Status: {history.status.status}. {history.status.reason || ''} Last session: {history.status.last_session_date || 'N/A'}. Last retrieval: {history.status.last_retrieved_at || 'N/A'}. Fetch: {history.status.last_fetch_status || 'never'}{history.status.last_error_code ? ` (${history.status.last_error_code})` : ''}. Rejected rows: {history.status.last_rejected_rows ?? 'N/A'}. Quality: {history.status.quality || 'N/A'}. Possible weekday gaps in recent history: {history.status.possible_weekday_gaps_last_60?.length ?? 0} (holidays unverified).</p>{last && <p className="caption">Raw O/H/L/C: {format(last.raw_open)} / {format(last.raw_high)} / {format(last.raw_low)} / {format(last.raw_close)}. Adjusted close: {format(last.adjusted_close)}. Volume: {format(last.volume)}. Retrieved: {last.retrieved_at}. <a href={last.source_url} target="_blank" rel="noreferrer">Yahoo source</a>. {last.contract_identity ? `Contract: ${last.contract_identity}; roll policy: ${last.roll_policy}.` : ''}</p>}<p className="caption">Macro cycles and official-release observations remain on the Inflection Monitor. Price history alone does not establish a macro feedback loop or an investable forecast.</p></section></div>
    <footer><span>RESEARCH DATA · PROVIDER RIGHTS REVIEW REQUIRED</span><span>No orders, options or trade recommendations.</span></footer>
  </main>;
}
