import Link from 'next/link';
import '../phase2.css';

type Evidence = { id: number; claim: string; value: string | null; value_numeric: number | null; unit: string | null; source: string; source_reference: string; period_end: string; reliability_note: string; stance: string };
type Candidate = { key: string; cycle_id: string; type: string; why_inflection: string; confirmation_required: string; invalidation: string; supporting_observations: Evidence[]; contradictory_evidence: Evidence[]; competing_explanations: string[] };
type Cycle = { id: string; name: string; state: string; material: boolean; explanation: string; candidate: Candidate | null; missing_mechanisms: string[]; supporting_evidence: Evidence[]; contradictory_evidence: Evidence[]; conflicting_source_observations: Evidence[]; competing_explanations: string[]; invalidation: string };
type Outlook = { instrument_id: string; instrument: string; horizon: string; direction: string; influences: { cycle_id: string; direction: string; influence: string; mechanism: string; invalidation: string }[]; opposing_mechanisms: string[]; priced_in: string; uncertainty: string; market_confirmation: { status: string; change_pct?: number; last_session?: string }; caveat?: string | null };
type Overview = { as_of: string; catalog_version: string; material_cycles: Cycle[]; cycles: Cycle[]; candidates: Candidate[]; outlooks: Outlook[]; investigations: { id: number; candidate_key: string; status: string }[]; verified_facts: { indicator_id: string; value: number; unit: string; period_end: string; source: string | null; interpretation: string }[]; evidence_count: number; warning: string };
type Catalog = { cycles: Record<string, { name: string; thesis: string; actors: string[]; incentives: string[]; mechanisms: { id: string; role: string; description: string }[]; alternatives: string[]; invalidated_when: string; unresolved: string }> };

async function beginInvestigation(form: FormData) {
  'use server';
  const token = String(form.get('operator_token') || '');
  const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const candidate = String(form.get('candidate_key') || '');
  const response = await fetch(`${api}/api/v1/research/investigations`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token }, body: JSON.stringify({ candidate_key: candidate, initial_observation: String(form.get('initial_observation') || ''), competing_hypotheses: [String(form.get('alternative') || '')], questions: ['Which independent observation would distinguish the competing mechanisms?'], confirmation_criteria: String(form.get('confirmation') || ''), falsification_criteria: String(form.get('invalidation') || '') }), cache: 'no-store' });
  if (!response.ok) throw new Error(`Investigation could not be started (API ${response.status}). Check operator scope and candidate evidence.`);
}

export default async function Intelligence({ searchParams }: { searchParams: Promise<{ as_of?: string }> }) {
  const params = await searchParams;
  const api = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const token = process.env.RESEARCH_OPERATOR_TOKEN;
  const catalogResponse = await fetch(`${api}/api/v1/research/catalog`, { cache: 'no-store' }).catch(() => null);
  const definitions: Catalog | null = catalogResponse?.ok ? await catalogResponse.json() : null;
  let data: Overview | null = null;
  if (token) {
    const query = params.as_of ? `?as_of=${encodeURIComponent(params.as_of)}` : '';
    const response = await fetch(`${api}/api/v1/research/overview${query}`, { headers: { 'X-Admin-Token': token }, cache: 'no-store' }).catch(() => null);
    if (response?.ok) data = await response.json();
  }
  return <main className="container">
    <header className="header"><div><div className="eyebrow">SMART HEDGE / PRIVATE RESEARCH</div><h1>Cycle intelligence</h1><p className="subtitle">Feedback mechanisms · potential inflections · conditional 1–6 month implications</p><Link href="/">Stress monitor →</Link></div><div className="header-right"><strong className="live-label">PRIVATE EXPLORATORY EVIDENCE</strong><span>{data?.as_of || 'No authorized assessment'}</span></div></header>
    {!data ? <section className="panel"><h2>Research assessment unavailable</h2><p>Private operator access or evidence is not configured for this environment. Existing verified and demonstration monitors remain available. No live macro conclusion is implied.</p></section> : <>
      <p className="caption">{data.warning} Catalog {data.catalog_version} · {data.evidence_count} research records. Observed facts and interpretations are kept separate.</p>
      <div className="section-heading"><div><div className="eyebrow">WHAT IS ACTIVE?</div><h2>Material cycle developments</h2></div></div>
      {data.material_cycles.length ? data.material_cycles.map(c => <details className="panel" key={c.id}><summary><strong>{c.name} · {c.state}</strong></summary><p>{c.explanation}</p><p>Missing: {c.missing_mechanisms.join(', ') || 'none in the current window'}</p><p>Conflicting source claims: {c.conflicting_source_observations.map(e => `${e.claim}: ${e.stance} (${e.source}, ${e.period_end})`).join('; ') || 'none'}</p><p>Alternative explanations: {c.competing_explanations.join('; ')}</p><p>Falsifier: {c.invalidation}</p>{c.supporting_evidence.length ? c.supporting_evidence.map(e => <p key={e.id}>Observed claim: {e.claim} · {e.value ?? e.value_numeric ?? 'unavailable'} {e.unit || ''} · {e.period_end}. <a href={e.source_reference} target="_blank" rel="noreferrer">{e.source}</a>. Caveat: {e.reliability_note}</p>) : <p>No current supporting observation.</p>}</details>) : <section className="panel"><p>No material cycle development is supported by current research evidence. All six hypotheses remain inspectable in the catalog.</p></section>}
      <div className="section-heading"><div><div className="eyebrow">WHAT MIGHT BE CHANGING?</div><h2>Inflection candidate inbox</h2></div></div>
      {data.candidates.length ? data.candidates.map(c => <details className="panel" key={c.key}><summary><strong>{c.cycle_id} · {c.type.replaceAll('_', ' ')}</strong></summary><p>{c.why_inflection}</p><p>Confirmation: {c.confirmation_required}</p><p>Contrary evidence: {c.contradictory_evidence.map(e => `${e.claim} (${e.source})`).join('; ') || 'none observed; absence is not contradiction'}</p><p>Alternatives: {c.competing_explanations.join('; ')}</p><p>Invalidation: {c.invalidation}</p><form action={beginInvestigation}><input type="hidden" name="candidate_key" value={c.key}/><input type="hidden" name="initial_observation" value={c.why_inflection}/><input type="hidden" name="alternative" value={c.competing_explanations[0] || 'Further independent cause to investigate'}/><input type="hidden" name="confirmation" value={c.confirmation_required}/><input type="hidden" name="invalidation" value={c.invalidation}/><label>Operator token <input type="password" name="operator_token" required autoComplete="off" /></label><button type="submit">Begin investigation</button></form></details>) : <section className="panel"><p>No persistent inflection candidate. One-off movements are not promoted automatically.</p></section>}
      {data.investigations.length > 0 && <section className="panel"><h2>Investigations</h2>{data.investigations.map(i => <p key={i.id}>#{i.id} · {i.candidate_key} · {i.status}</p>)}</section>}
      {definitions && <section className="panel"><h2>All six mechanism hypotheses</h2>{Object.entries(definitions.cycles).map(([id, c]) => <details key={id}><summary>{c.name} · {data.cycles.find(x => x.id === id)?.state || 'indeterminate'}</summary><p>{c.thesis}</p><p>Actors: {c.actors.join(', ')}. Incentives: {c.incentives.join(', ')}.</p>{c.mechanisms.map(m => <p key={m.id}>{m.role}: {m.description}</p>)}<p>Alternatives: {c.alternatives.join('; ')}. Falsifier: {c.invalidated_when}</p><p>Unresolved: {c.unresolved}</p></details>)}</section>}
      <section className="panel"><h2>Observed verified facts, separate from interpretation</h2>{data.verified_facts.length ? data.verified_facts.map(f => <p key={f.indicator_id}>{f.indicator_id}: {f.value} {f.unit} ({f.period_end}; {f.source || 'source reference unavailable'}). {f.interpretation}</p>) : <p>No governed observation is currently known to this private environment.</p>}</section>
      <div className="section-heading"><div><div className="eyebrow">WHAT DOES IT MEAN?</div><h2>Conditional market outlook</h2></div></div>
      {data.outlooks.filter(o => ['nifty50', 'brent_front_yahoo', 'wti_front_yahoo', 'usd_inr_yahoo', 'gold_front_yahoo'].includes(o.instrument_id)).map(o => <details className="panel" key={`${o.instrument_id}-${o.horizon}`}><summary><strong>{o.instrument} · {o.horizon} · {o.direction}</strong></summary><p>{o.influences.map(i => `${i.cycle_id}: ${i.direction} (${i.influence})`).join('; ') || 'No supported directional cycle; investigate conditional scenarios.'}</p><p>Opposing mechanisms: {o.opposing_mechanisms.join(', ') || 'unknown'}. Already priced in: {o.priced_in}.</p><p>Market confirmation: {o.market_confirmation.status}{o.market_confirmation.change_pct == null ? '' : ` · observed ${o.market_confirmation.change_pct}% over stored period`}. {o.caveat}</p><p>Uncertainty: {o.uncertainty}</p></details>)}
    </>}
  </main>;
}
