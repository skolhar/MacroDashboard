import './capital-flows.css';

type Exclusions = { future_dated?: number; late_ingested?: number };
type Freshness = { latest_period_end?: string | null; days_behind_as_of?: number | null };
type Offset = { state: string; as_of: string; matched_sessions?: number; fpi_net_cr?: number; dii_net_cr?: number; offset_size_cr?: number; unmatched_sessions_excluded?: number; gross_rows_excluded?: number; basis?: string } | null;
type Persistence = { state: string; persistence: string; offset_ratio?: number; as_of?: string; detection?: { sessions?: number; dii_daily_avg_cr?: number; semantics?: string }; follow_up?: { sessions?: number; required?: number; dii_daily_avg_cr?: number; semantics?: string } } | null;
type Sip = { state: string; avg_sip_cr_after_rising_returns?: number | null; avg_sip_cr_after_falling_returns?: number | null; avg_sip_mom_growth_pct_after_rising_returns?: number | null; avg_sip_mom_growth_pct_after_falling_returns?: number | null; median_sip_mom_growth_pct?: number | null; lag_months?: number; months_observed?: number; rising_return_months?: number; falling_return_months?: number; limited_directions?: boolean; months_skipped_missing_returns?: number; months_skipped_missing_prior_sip?: number; basis?: string } | null;
type Spurious = { state: string; reason?: string; forward_return_pct?: number; forward_months?: number; caveat?: string } | null;
type View = {
  as_of: string;
  state: string;
  vintage_mode?: string;
  reason?: string;
  required_series?: string[];
  offset: Offset;
  persistence: Persistence;
  sip_response: Sip;
  spurious_check: Spurious;
  excluded_observations?: Record<string, Exclusions>;
  data_freshness?: Record<string, Freshness>;
  observed_vs_hypothesized?: { observed?: string[]; hypothesized_not_observed?: string[] };
  limitation: string;
};
const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
const fmt = (n: number | null | undefined, digits = 1) => n == null ? 'N/A' : n.toLocaleString('en-IN', { maximumFractionDigits: digits });
const pct = (n: number | null | undefined, digits = 2) => n == null ? 'N/A' : `${n.toLocaleString('en-IN', { maximumFractionDigits: digits })}%`;

function Panel({ title, children, note }: { title: string; children?: React.ReactNode; note?: string }) {
  return <section className="panel" aria-label={title}><h2>{title}</h2>{note && <p className="muted">{note}</p>}{children}</section>;
}

function Unavailable({ reason }: { reason?: string }) {
  return <div className="empty">DATA UNAVAILABLE · {reason || 'no attributable observations stored'}</div>;
}

function FreshnessRow({ label, fresh }: { label: string; fresh?: Freshness }) {
  if (!fresh) return null;
  return <tr><th>{label}</th><td>latest {fresh.latest_period_end || 'none'} · {fresh.days_behind_as_of == null ? 'unknown' : `${fresh.days_behind_as_of} days behind as-of`}</td></tr>;
}

function ExclusionRow({ label, ex }: { label: string; ex?: Exclusions }) {
  if (!ex) return null;
  const future = ex.future_dated || 0;
  const late = ex.late_ingested || 0;
  if (!future && !late) return null;
  return <tr><th>{label}</th><td>{future} future-dated · {late} ingested after the knowledge cutoff (excluded)</td></tr>;
}
import './capital-flows.css';

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
  const ovh = data.observed_vs_hypothesized;
  return <main className="container">
    <h1>Capital-flow investigation</h1>
    <p className="muted">Evidence-first view of attributable FPI/DII and household (SIP) flow behaviour. Every finding below is descriptive co-occurrence, not established causation.</p>
    <div className="summary-stat"><span>As of</span><strong>{data.as_of}</strong><small>state: {data.state}{data.vintage_mode ? ` · knowledge mode: ${data.vintage_mode}` : ''}</small></div>
    <Panel title="Offset: DII buying against FPI selling" note="Co-occurrence of opposite-sign net flows over identical reporting sessions only — unmatched sessions are excluded, never zero-filled, and no order, motivation or intent is inferred.">
      {available && data.offset ? (
        <table aria-label="FPI/DII offset detail">
          <tbody>
            <tr><th>State</th><td>{data.offset.state}</td></tr>
            <tr><th>Window</th><td>{fmt(data.offset.matched_sessions, 0)} matched sessions ending {data.offset.as_of}</td></tr>
            <tr><th>FPI net (₹ crore)</th><td>{fmt(data.offset.fpi_net_cr, 0)}</td></tr>
            <tr><th>DII net (₹ crore)</th><td>{fmt(data.offset.dii_net_cr, 0)}</td></tr>
            <tr><th>Offset size (₹ crore)</th><td>{fmt(data.offset.offset_size_cr, 0)}</td></tr>
            <tr><th>Excluded</th><td>{data.offset.unmatched_sessions_excluded || 0} unmatched sessions · {data.offset.gross_rows_excluded || 0} gross-turnover rows</td></tr>
          </tbody>
        </table>
      ) : <Unavailable reason={data.reason} />}
    </Panel>
    <Panel title="Absorption persistence" note="The detection is the signal observable on its date; the follow-up is a retrospective assessment using evidence available only afterwards — the two are never presented as one signal.">
      {available && data.persistence ? (
        <div>
          <p className="result">{data.persistence.state} · offset ratio {fmt(data.persistence.offset_ratio, 3)}</p>
          <table aria-label="Persistence detail">
            <tbody>
              <tr><th>Detection</th><td>{fmt(data.persistence.detection?.sessions, 0)} sessions · daily-average DII {fmt(data.persistence.detection?.dii_daily_avg_cr, 0)} ₹ crore ({data.persistence.detection?.semantics})</td></tr>
              <tr><th>Follow-up</th><td>{fmt(data.persistence.follow_up?.sessions, 0)}/{fmt(data.persistence.follow_up?.required, 0)} sessions · daily-average DII {fmt(data.persistence.follow_up?.dii_daily_avg_cr, 0)} ₹ crore ({data.persistence.follow_up?.semantics})</td></tr>
            </tbody>
          </table>
        </div>
      ) : <Unavailable reason={data.reason} />}
    </Panel>
    <Panel title="Household SIP response" note="Monthly SIP contributions compared against index returns from the configured lag earlier. Returns precede contributions, so this is co-movement only; long-run contribution growth is reported separately because it can dominate a level comparison, and gross instalment flows cannot distinguish registrations, discontinuations or switches.">
      {available && data.sip_response ? (
        <table aria-label="SIP response detail">
          <tbody>
            <tr><th>State</th><td>{data.sip_response.state}{data.sip_response.limited_directions ? ' · limited return observations in one or both directions' : ''}</td></tr>
            <tr><th>Response lag (months)</th><td>{fmt(data.sip_response.lag_months, 0)}</td></tr>
            <tr><th>Avg SIP after rising returns</th><td>{fmt(data.sip_response.avg_sip_cr_after_rising_returns, 0)} ₹ crore</td></tr>
            <tr><th>Avg SIP after falling returns</th><td>{fmt(data.sip_response.avg_sip_cr_after_falling_returns, 0)} ₹ crore</td></tr>
            <tr><th>Avg MoM growth after rising returns</th><td>{pct(data.sip_response.avg_sip_mom_growth_pct_after_rising_returns)}</td></tr>
            <tr><th>Avg MoM growth after falling returns</th><td>{pct(data.sip_response.avg_sip_mom_growth_pct_after_falling_returns)}</td></tr>
            <tr><th>Median MoM SIP growth (long-run)</th><td>{pct(data.sip_response.median_sip_mom_growth_pct)}</td></tr>
            <tr><th>Months observed</th><td>{fmt(data.sip_response.months_observed, 0)} · {data.sip_response.rising_return_months || 0} rising / {data.sip_response.falling_return_months || 0} falling</td></tr>
            <tr><th>Skipped</th><td>{data.sip_response.months_skipped_missing_returns || 0} missing-return · {data.sip_response.months_skipped_missing_prior_sip || 0} missing-prior-SIP</td></tr>
          </tbody>
        </table>
      ) : <Unavailable reason={data.reason} />}
    </Panel>
    <Panel title="Spurious-association check" note="A 'response' claim requires a complete forward return month and comparable observations; same-session flows are co-occurrence because reporting timestamps cannot establish trading order.">
      {available && data.spurious_check ? <p className="result">{data.spurious_check.state}{data.spurious_check.reason ? ` · ${data.spurious_check.reason}` : ''}{data.spurious_check.forward_return_pct != null ? ` · compounded forward return ${pct(data.spurious_check.forward_return_pct)} over ${data.spurious_check.forward_months || 0} month(s)` : ''}{data.spurious_check.caveat ? ` · ${data.spurious_check.caveat}` : ''}</p> : <Unavailable reason={data.reason} />}
    </Panel>
    {available && (data.excluded_observations || data.data_freshness) ? (
      <Panel title="Data quality and point-in-time exclusions" note="Rows dated after the as-of time or ingested after the knowledge cutoff are excluded, never silently selected as if they were originally known.">
        <table aria-label="Data quality and exclusions">
          <tbody>
            <FreshnessRow label="FPI freshness" fresh={data.data_freshness?.fpi} />
            <FreshnessRow label="DII freshness" fresh={data.data_freshness?.dii} />
            <FreshnessRow label="SIP freshness" fresh={data.data_freshness?.sip} />
            <FreshnessRow label="Index freshness" fresh={data.data_freshness?.returns} />
            <ExclusionRow label="FPI excluded" ex={data.excluded_observations?.fpi} />
            <ExclusionRow label="DII excluded" ex={data.excluded_observations?.dii} />
            <ExclusionRow label="SIP excluded" ex={data.excluded_observations?.sip} />
            <ExclusionRow label="Index excluded" ex={data.excluded_observations?.returns} />
          </tbody>
        </table>
      </Panel>
    ) : null}
    {available && ovh ? (
      <Panel title="Observed versus hypothesised" note="Only the observed list is supported by stored observations; everything in the second list is a hypothesis awaiting independently dated actor-response evidence.">
        {ovh.observed?.length ? <p className="result">Observed: {ovh.observed.join('; ')}</p> : null}
        {ovh.hypothesized_not_observed?.length ? <p className="result limitation">Hypothesised, not observed: {ovh.hypothesized_not_observed.join('; ')}</p> : null}
      </Panel>
    ) : null}
    <Panel title="Limitations"><p className="result limitation">{data.limitation}</p></Panel>
    <form className="filters" action="/intelligence/capital-flows" method="get" aria-label="Investigation filters"><label>As-of timestamp (ISO) <input type="text" name="as_of" defaultValue={params.as_of || ''} /></label><button type="submit">Apply</button></form>
  </main>;
}
