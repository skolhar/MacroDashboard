import './capital-flows.css';

type Offset = { state: string; as_of: string; sessions?: number; fpi_net_cr?: number; dii_net_cr?: number; offset_size_cr?: number; basis?: string } | null;
type Persistence = { state: string; persistence: string; offset_ratio?: number; as_of?: string } | null;
type Sip = { state: string; avg_sip_cr_rising_months?: number; avg_sip_cr_falling_months?: number; months_observed?: number; basis?: string } | null;
type Spurious = { state: string; reason?: string; forward_return_pct?: number; caveat?: string } | null;
type View = {
  as_of: string;
  state: string;
  reason?: string;
  required_series?: string[];
  offset: Offset;
  persistence: Persistence;
  sip_response: Sip;
  spurious_check: Spurious;
  limitation: string;
};
const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
const fmt = (n: number | null | undefined, digits = 1) => n == null ? 'N/A' : n.toLocaleString('en-IN', { maximumFractionDigits: digits });

function Panel({ title, children, note }: { title: string; children?: React.ReactNode; note?: string }) {
  return <section className="panel" aria-label={title}><h2>{title}</h2>{note && <p className="muted">{note}</p>}{children}</section>;
}

function Unavailable({ reason }: { reason?: string }) {
  return <div className="empty">DATA UNAVAILABLE · {reason || 'no attributable observations stored'}</div>;
}

export default async function CapitalFlows({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const params = await searchParams;
  const query = new URLSearchParams(); if (params.as_of) query.set('as_of', params.as_of);
  let data: View;
  try {
    const res = await fetch(`${api}/api/v1/capital-flows?${query}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(String(res.status));
    data = await res.json();
  } catch {
    data = { as_of: params.as_of || 'now', state: 'api_unavailable', offset: null, persistence: null, sip_response: null, spurious_check: null, limitation: 'The private API could not be reached; no investigation shown.' };
  }
  const available = data.state === 'investigation_available';
  return <main className="container">
    <h1>Capital-flow investigation</h1>
    <p className="muted">Evidence-first view of attributable FPI/DII and household (SIP) flow behaviour. Every finding below is descriptive co-occurrence, not established causation.</p>
    <div className="summary-stat"><span>As of</span><strong>{data.as_of}</strong><small>state: {data.state}</small></div>
    <Panel title="Offset: DII buying against FPI selling" note="Co-occurrence of opposite-sign net flows only — no order, motivation or intent is inferred.">
      {available && data.offset ? (
        <table aria-label="FPI/DII offset detail">
          <tbody>
            <tr><th>State</th><td>{data.offset.state}</td></tr>
            <tr><th>Window</th><td>{fmt(data.offset.sessions, 0)} sessions ending {data.offset.as_of}</td></tr>
            <tr><th>FPI net (₹ crore)</th><td>{fmt(data.offset.fpi_net_cr, 0)}</td></tr>
            <tr><th>DII net (₹ crore)</th><td>{fmt(data.offset.dii_net_cr, 0)}</td></tr>
            <tr><th>Offset size (₹ crore)</th><td>{fmt(data.offset.offset_size_cr, 0)}</td></tr>
          </tbody>
        </table>
      ) : <Unavailable reason={data.reason} />}
    </Panel>
    <Panel title="Absorption persistence" note="Whether domestic buying sustains, weakens or not_offsetting against continued foreign selling in subsequent sessions.">
      {available && data.persistence ? <p className="result">{data.persistence.state} · offset ratio {fmt(data.persistence.offset_ratio, 3)}</p> : <Unavailable reason={data.reason} />}
    </Panel>
    <Panel title="Household SIP response" note="Monthly co-movement between SIP contributions and subsequent equity returns. Household motivation is not observed.">
      {available && data.sip_response ? (
        <table aria-label="SIP response detail">
          <tbody>
            <tr><th>State</th><td>{data.sip_response.state}</td></tr>
            <tr><th>Avg SIP in rising-return months</th><td>{fmt(data.sip_response.avg_sip_cr_rising_months, 0)} ₹ crore</td></tr>
            <tr><th>Avg SIP in falling-return months</th><td>{fmt(data.sip_response.avg_sip_cr_falling_months, 0)} ₹ crore</td></tr>
            <tr><th>Months observed</th><td>{fmt(data.sip_response.months_observed, 0)}</td></tr>
          </tbody>
        </table>
      ) : <Unavailable reason={data.reason} />}
    </Panel>
    <Panel title="Spurious-association check" note="A 'response' claim requires strict temporal order plus a forward return window; anything else is reported as unresolved.">
      {available && data.spurious_check ? <p className="result">{data.spurious_check.state}{data.spurious_check.reason ? ` · ${data.spurious_check.reason}` : ''}{data.spurious_check.caveat ? ` · ${data.spurious_check.caveat}` : ''}</p> : <Unavailable reason={data.reason} />}
    </Panel>
    <Panel title="Limitations"><p className="result limitation">{data.limitation}</p></Panel>
    <form className="filters" action="/intelligence/capital-flows" method="get" aria-label="Investigation filters"><label>As-of timestamp (ISO) <input type="text" name="as_of" defaultValue={params.as_of || ''} /></label><button type="submit">Apply</button></form>
  </main>;
}
