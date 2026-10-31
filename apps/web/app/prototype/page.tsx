import { loadMarkets } from "./market";

export const dynamic = "force-dynamic";
const pretty=(n:number|null)=>n===null?"N/A":n.toLocaleString("en-IN",{maximumFractionDigits:2});
export default async function ResearchPrototype(){
 const {cards,anomalies,errors,asOf}=await loadMarkets();
 const visible=cards.filter(x=>x.id!=="gold");
 return <main style={{maxWidth:1030,margin:"35px auto",padding:"0 24px",fontFamily:"system-ui",lineHeight:1.55}}>
  <p style={{letterSpacing:2,fontSize:12,fontWeight:700}}>SMARTHEDGE / SECONDARY-DATA RESEARCH</p>
  <h1>Market Intelligence</h1>
  <p>Actual Yahoo Finance end-of-day history, refreshed at most every six hours. Price-only experimental model, <strong>not the validated macro reflexivity model</strong>. No broker connection, orders or options execution.</p>
  <p style={{fontSize:13,opacity:.8}}>Page evaluated {new Date(asOf).toLocaleString("en-IN",{timeZone:"Asia/Kolkata"})} IST. Symbols are USD/INR, Nifty 50 and WTI futures proxy; WTI is not the MCX contract.</p>
  <section aria-label="Medium term market trends"><h2>1–6 month market trends</h2>
   <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(240px,1fr))",gap:14}}>
    {visible.map(c=><article key={c.id} style={{border:"1px solid #8b8b8b88",borderRadius:12,padding:18}}>
      <h3>{c.name}</h3><p style={{fontSize:22,fontWeight:700}}>{c.trend}</p>
      <p>Latest: {pretty(c.lastPrice)} {c.currency} <small>({c.lastDate||"unavailable"})</small></p>
      <p>1m: {pretty(c.oneMonth)}% · 3m: {pretty(c.threeMonth)}% · 6m: {pretty(c.sixMonth)}%</p>
      <p>63-session annualised volatility: {pretty(c.volatility)}%</p>
      <details><summary>Method and source</summary><p>{c.reason}</p><p>{c.source}; {c.bars} valid daily observations. Yahoo can revise/back-adjust data.</p></details>
     </article>)}
   </div>
  </section>
  <section aria-label="Persistent anomalies" style={{marginTop:30}}><h2>Persistent price anomalies</h2>
   {anomalies.length?anomalies.map(a=><article key={a.id} style={{border:"1px solid #8b8b8b88",borderRadius:12,padding:18,marginBottom:10}}>
    <h3>{a.title}</h3><p>{a.detail}</p>
    <details><summary>Start collaborative investigation</summary>
      <p>Verify original data and historical robustness. Investigate competing explanations, gather independently dated evidence, test disconfirming hypotheses, then decide whether to nominate a new cycle. This is a research prompt, not an automatic investigation or confirmed cycle.</p>
    </details>
   </article>):<p>No qualifying 10-session deviation detected in available histories. This is not an all-clear for economic risk.</p>}
  </section>
  <section aria-label="Known cycles" style={{marginTop:30}}><h2>Known macro cycles</h2><p>The existing <a href="/">reflexivity monitor</a> continues to show its independent cycle data. Yahoo price trends are deliberately <strong>not</strong> being inserted into governed macro observations or used to fabricate macro influence weights.</p></section>
  <section aria-label="ETF signals" style={{marginTop:30}}><h2>ETF attention</h2><p>Not yet assessed: reliable full-universe prices, NAV and trading-quality data are still required. Portfolio holdings will not automatically produce alerts.</p></section>
  {errors.length>0&&<section role="status" style={{marginTop:22}}><h2>Source availability</h2><p>Some Yahoo requests failed. No simulated replacements were used:</p><ul>{errors.map(x=><li key={x}>{x}</li>)}</ul></section>}
  <footer style={{marginTop:35,borderTop:"1px solid #8885",paddingTop:12,fontSize:12}}>Private research use only, subject to Yahoo Finance data terms. Public redistribution/production hosting requires separate rights review. Do not rely on this prototype for transactions.</footer>
 </main>;
}
