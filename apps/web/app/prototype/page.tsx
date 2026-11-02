"use client";
import { useState } from "react";

type Signal = { name: string; horizon: string; trend: "Improving" | "Weakening" | "Mixed"; evidence: string; confidence: string };
const examples: Signal[] = [
  { name: "Nifty 50", horizon: "1–6 months", trend: "Mixed", evidence: "Earnings momentum and domestic liquidity disagree in this sample.", confidence: "Illustrative" },
  { name: "Crude (WTI proxy)", horizon: "1–6 months", trend: "Weakening", evidence: "Sample inventory and demand indicators point to softer conditions.", confidence: "Illustrative" },
  { name: "USD/INR", horizon: "1–6 months", trend: "Improving", evidence: "Sample external funding pressure has increased; direction is USD versus INR.", confidence: "Illustrative" }
];
export default function PrototypePage() {
  const [investigate, setInvestigate] = useState(false);
  return <main style={{maxWidth:960,margin:"40px auto",padding:"0 20px",fontFamily:"system-ui"}}>
    <p style={{fontWeight:700,letterSpacing:2}}>SMARTHEDGE · OFFLINE PROTOTYPE</p>
    <h1>What needs attention?</h1>
    <p>This is a <strong>synthetic demonstration</strong>. No live market observations, brokerage connections, or investment recommendations.</p>
    <section aria-label="Medium-term market outlook"><h2>Market trends</h2>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(220px,1fr))",gap:12}}>
      {examples.map(s=><article key={s.name} style={{border:"1px solid #8886",borderRadius:12,padding:18}}>
        <h3>{s.name}</h3><p><strong>{s.trend}</strong> · {s.horizon}</p><p>{s.evidence}</p>
        <small>Confidence: {s.confidence} · Demo data only</small>
      </article>)}</div>
    </section>
    <section style={{marginTop:32}} aria-label="Known cycle changes"><h2>Known-cycle monitor</h2>
      <p>Sample attention item: energy-demand cycle influence changed for crude. Evidence and weightage are not calibrated.</p>
      <p>Quantitative cycle weights: <strong>N/A</strong> until point-in-time validation.</p>
    </section>
    <section style={{marginTop:32}} aria-label="Persistent anomalies"><h2>Persistent anomalies</h2>
      <article style={{border:"1px solid #8886",borderRadius:12,padding:18}}>
        <h3>Gold versus real yields · sample candidate</h3>
        <p>Illustrative divergence; persistence has not been tested against actual observations.</p>
        <button type="button" onClick={()=>setInvestigate(v=>!v)}>{investigate?"Close investigation":"Investigate together"}</button>
        {investigate&&<div style={{marginTop:12}} role="region" aria-label="Collaborative investigation starter">
          <p><strong>Investigation opened locally (not saved).</strong> Verify the divergence first. Competing hypotheses: reserve buying, geopolitical hedging, ETF flows, or model misspecification.</p>
          <p>Next: gather dated independent evidence and falsifying observations before proposing a cycle.</p>
        </div>}
      </article>
    </section>
    <section style={{marginTop:32}} aria-label="ETF attention"><h2>ETF attention</h2>
      <p>Not assessed: no validated ETF price, NAV, or universe coverage. Portfolio holdings are not automatically highlighted.</p>
    </section>
    <footer style={{marginTop:40,fontSize:13,opacity:.7}}>No options execution · No orders · No automatic cycle promotion · No external APIs</footer>
  </main>;
}
