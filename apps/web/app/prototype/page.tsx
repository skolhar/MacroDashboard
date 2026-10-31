'use client';

import './prototype.css';

import { useMemo, useState } from 'react';

type Observation = { day: number; value: number };
type Instrument = { id: string; title: string; description: string; unit: string; observations: Observation[]; drivers: string[] };
type Anomaly = { id: string; title: string; description: string; evidence: string; caveat: string; instrument: string };
const generate = (base: number, slope: number, wiggle: number): Observation[] =>
  Array.from({ length: 120 }, (_, day) => ({
    day, value: +(base + slope * day + Math.sin(day / 6) * wiggle + Math.cos(day / 13) * wiggle * .6).toFixed(3),
  }));
// Deliberately fabricated teaching fixtures, never market quotes.
const instruments: Instrument[] = [
  { id: 'nifty', title: 'Nifty 50', description: 'Indian equity regime', unit: 'synthetic index points', observations: generate(24000, 12, 260), drivers: ['Earnings revision breadth', 'Liquidity and foreign flows', 'Oil and inflation'] },
  { id: 'crude', title: 'WTI crude proxy', description: 'Global oil regime; not MCX contract data', unit: 'synthetic USD/bbl', observations: generate(77, -.075, 2.4), drivers: ['Global demand', 'Physical supply and OPEC+', 'Inventories'] },
  { id: 'fx', title: 'USD/INR', description: 'Currency context only · no trade recommendations', unit: 'synthetic INR per USD', observations: generate(84, .016, .38), drivers: ['Dollar / US rates', 'External flows', 'Oil import cost'] },
];
const anomalies: Anomaly[] = [
  { id: 'gold', title: 'Gold vs real yields', description: 'Illustrative 12-week divergence between gold momentum and a conventional real-yield headwind.', evidence: 'Gold relative strength stayed positive in a constructed sample while real yields increased.', caveat: 'A divergence is not proof of dedollarisation; test central-bank demand, ETF flows and positioning.', instrument: 'Gold ETFs' },
  { id: 'growth', title: 'GDP vs activity', description: 'Illustrative persistent divergence between headline growth and several physical activity proxies.', evidence: 'In the constructed example, physical activity slows across consecutive releases.', caveat: 'Check seasonality, revisions, deflators and whether indicators measure comparable output.', instrument: 'Nifty 50 / equity ETFs' },
];

function summarize(rows: Observation[], days: number) {
  const last = rows.at(-1)?.value;
  const previous = rows.at(-1 - days)?.value;
  if (last == null || previous == null || previous === 0) return { change: null as number | null, regime: 'Unavailable' };
  const change = 100 * (last / previous - 1);
  // Illustrative thresholds, deliberately NOT investment-model calibration.
  return { change, regime: change > 1.5 ? 'Rising' : change < -1.5 ? 'Falling' : 'Mixed / range' };
}
function Sparkline({ rows }: { rows: Observation[] }) {
  const min = Math.min(...rows.map(p => p.value));
  const max = Math.max(...rows.map(p => p.value));
  const spread = max - min || 1;
  const points = rows.map((r, i) => `${(i / (rows.length - 1) * 100).toFixed(2)},${(42 - (r.value - min) / spread * 35).toFixed(2)}`).join(' ');
  return <svg viewBox="0 0 100 48" preserveAspectRatio="none" role="img" aria-label="Illustrative synthetic price history"><polyline points={points} fill="none" stroke="#6bd2c8" strokeWidth="1.5" vectorEffect="non-scaling-stroke" /></svg>;
}

export default function Prototype() {
  const [horizon, setHorizon] = useState<'short' | 'medium'>('medium');
  const [selected, setSelected] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [saved, setSaved] = useState<Record<string, string>>({});
  const lookback = horizon === 'medium' ? 90 : 20;
  const displayed = useMemo(() => instruments.map(instrument => ({ ...instrument, signal: summarize(instrument.observations, lookback) })), [lookback]);
  const selectedAnomaly = anomalies.find(a => a.id === selected);
  return <main className="container prototype">
    <header className="header"><div><div className="eyebrow">SMART HEDGE / NO-BROKERAGE PROTOTYPE</div><h1>Market attention radar</h1><p className="subtitle">Three market trends · persistent anomalies · user-led investigation</p><a href="/">← Existing macro dashboard</a></div><div className="header-right"><strong className="demo">DEMO · SYNTHETIC, NOT MARKET DATA</strong><span>No accounts, credentials, trading or external feed required</span></div></header>
    <section className="prototype-disclaimer" role="status"><strong>Demonstration only.</strong> All prices, changes, thresholds and anomalies are fabricated examples to test the workflow. No live signals, real economic conclusions or investment recommendations are shown.</section>
    <section className="panel">
      <div className="panel-heading"><div><div className="eyebrow">ILLUSTRATIVE MOMENTUM, NOT PREDICTION</div><h2>Nifty · Crude · USD/INR</h2></div><div className="prototype-switch" aria-label="Select horizon"><button className={horizon === 'short' ? 'active' : ''} onClick={() => setHorizon('short')}>20 sessions</button><button className={horizon === 'medium' ? 'active' : ''} onClick={() => setHorizon('medium')}>90 sessions</button></div></div>
      <div className="prototype-grid">{displayed.map(item => <article className="prototype-tile" key={item.id}><div className="prototype-tile-top"><h3>{item.title}</h3><span className="pill neutral">{item.signal.regime}</span></div><p className="muted">{item.description}</p><Sparkline rows={item.observations.slice(-lookback)} /><div className="prototype-number">{item.signal.change == null ? 'N/A' : `${item.signal.change > 0 ? '+' : ''}${item.signal.change.toFixed(2)}%`}</div><small className="muted">Synthetic {lookback}-session change · {item.unit}</small><details><summary>Context to monitor</summary><ul>{item.drivers.map(d => <li key={d}>{d}</li>)}</ul><p className="caption">Driver influence not yet calibrated; price change alone does not establish causation.</p></details></article>)}</div>
    </section>
    <section className="panel">
      <div className="panel-heading"><div><div className="eyebrow">EXCEPTION-FIRST RESEARCH</div><h2>Persistent anomalies</h2></div><span className="pill neutral">2 synthetic examples</span></div>
      <p className="muted">Anomaly detection is a separate research workflow. No cycle hypothesis is accepted automatically.</p>
      <div className="prototype-anomalies">{anomalies.map(item => <article className="prototype-alert" key={item.id}><div><h3>{item.title}</h3><p>{item.description}</p><small className="muted">Relevant exposure: {item.instrument}</small></div><button type="button" onClick={() => { setSelected(item.id); setNotes(saved[item.id] || ''); }}>Investigate</button></article>)}</div>
      {selectedAnomaly && <section className="prototype-investigation" aria-label="Collaborative investigation"><div className="prototype-tile-top"><h3>Investigating: {selectedAnomaly.title}</h3><button onClick={() => setSelected(null)}>Close</button></div><p><strong>Observed in the example:</strong> {selectedAnomaly.evidence}</p><p><strong>Competing explanation / falsification:</strong> {selectedAnomaly.caveat}</p><label htmlFor="research-notes">Your research notes (stored in this page only; no server persistence)</label><textarea id="research-notes" rows={3} value={notes} onChange={e => setNotes(e.target.value)} placeholder="Hypotheses, contradictory evidence, next sources to examine..." /><button onClick={() => setSaved(old => ({ ...old, [selectedAnomaly.id]: notes }))}>Keep notes during this session</button>{saved[selectedAnomaly.id] !== undefined && <small className="muted">Notes retained in browser memory until you reload this page.</small>}</section>}
    </section>
    <section className="panel"><div className="eyebrow">ETF ATTENTION</div><h2>No ETF alerts generated</h2><p className="muted">No ETF market or NAV data is connected. This is <strong>unassessable coverage</strong>, not a claim that your holdings or outside opportunities are safe.</p></section>
    <footer><strong>RESEARCH PROTOTYPE · SYNTHETIC FIXTURES ONLY</strong><span>No brokerage integration or real-time requirement</span></footer>
  </main>;
}
