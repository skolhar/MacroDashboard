export type Trend = "Uptrend" | "Downtrend" | "Mixed" | "Insufficient data";
export type MarketCard = {
  id:string; name:string; symbol:string; lastDate:string|null; currency:string;
  lastPrice:number|null; trend:Trend; oneMonth:number|null; threeMonth:number|null;
  sixMonth:number|null; volatility:number|null; confidence:string;
  reason:string; bars:number; source:string;
};
export type Anomaly = { id:string; title:string; detail:string; duration:number; affected:string[] };
type Candle = { date:string; close:number };
const TICKERS = [
  {id:"nifty", name:"Nifty 50", symbol:"^NSEI"},
  {id:"crude", name:"WTI crude futures proxy", symbol:"CL=F"},
  {id:"fx", name:"USD/INR", symbol:"INR=X"},
  {id:"gold", name:"Gold futures proxy", symbol:"GC=F"},
];
function pct(now:number, before:number):number {return +(100*(now/before-1)).toFixed(2)}
function periodReturn(c:Candle[], days:number):number|null {
  return c.length>days ? pct(c.at(-1)!.close,c.at(-days-1)!.close):null;
}
export function assess(id:string,name:string,symbol:string,c:Candle[],currency=""):MarketCard {
  const last=c.at(-1), one=periodReturn(c,21),three=periodReturn(c,63),six=periodReturn(c,126);
  const recent=c.slice(-63);
  const changes=recent.slice(1).map((x,i)=>Math.log(x.close/recent[i].close));
  const mean=changes.reduce((a,b)=>a+b,0)/(changes.length||1);
  const variance=changes.reduce((a,b)=>a+(b-mean)**2,0)/(changes.length||1);
  const vol=changes.length>=40?+(100*Math.sqrt(252*variance)).toFixed(1):null;
  const enough=c.length>=150&&three!==null&&six!==null;
  const directions=[one,three,six].filter((v):v is number=>v!==null).map(v=>Math.sign(v));
  const pos=directions.filter(v=>v>0).length,neg=directions.filter(v=>v<0).length;
  const trend:Trend=!enough?"Insufficient data":pos>=2&&three!>0&&six!>0?"Uptrend":neg>=2&&three!<0&&six!<0?"Downtrend":"Mixed";
  return {id,name,symbol,lastDate:last?.date??null,currency,lastPrice:last?.close??null,trend,
    oneMonth:one,threeMonth:three,sixMonth:six,volatility:vol,bars:c.length,
    confidence:enough?"Experimental · price-only":"Insufficient history",
    reason:!enough?"At least 150 valid daily observations are required.":`21/63/126-session returns: ${one}% / ${three}% / ${six}%. This is a price-only trend rule, not the macro-cycle model.`,
    source:"Yahoo Finance chart history · unverified secondary data"};
}
export function detectAnomalies(cards:MarketCard[],series:Record<string,Candle[]>):Anomaly[] {
  const out:Anomaly[]=[];
  // Candidate: price persistently far from its own rolling mean, independent of news narratives.
  for(const card of cards){
    const bars=series[card.id]||[];
    if(bars.length<150)continue;
    const tests:number[]=[];
    for(let i=bars.length-10;i<bars.length;i++){
      const window=bars.slice(i-60,i);
      if(window.length<60)break;
      const logs=window.map(x=>Math.log(x.close));
      const m=logs.reduce((a,b)=>a+b,0)/logs.length;
      const sd=Math.sqrt(logs.reduce((a,b)=>a+(b-m)**2,0)/logs.length);
      tests.push(sd>0?(Math.log(bars[i].close)-m)/sd:0);
    }
    if(tests.length===10&&tests.every(z=>z>=2)||tests.length===10&&tests.every(z=>z<=-2)){
      const z=tests.at(-1)!;
      out.push({id:card.id,title:`${card.name}: persistent ${z>0?"positive":"negative"} deviation`,
        detail:`Daily log price was more than two trailing 60-session standard deviations ${z>0?"above":"below"} its prior mean for 10 consecutive sessions. This is a screening anomaly, not a causal cycle.`,
        duration:10,affected:[card.name]});
    }
  }
  return out;
}
export async function loadMarkets():Promise<{cards:MarketCard[];anomalies:Anomaly[];errors:string[];asOf:string}> {
  const series:Record<string,Candle[]>={};const errors:string[]=[];
  const cards=await Promise.all(TICKERS.map(async ({id,name,symbol})=>{
    try {
      const url=`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=2y&interval=1d`;
      const r=await fetch(url,{next:{revalidate:21600},headers:{"User-Agent":"Mozilla/5.0 (compatible; SmartHedgeResearch/1.0)"}});
      if(!r.ok)throw Error(`HTTP ${r.status}`);
      const json=await r.json();
      const x=json?.chart?.result?.[0];
      if(!x?.timestamp||!x.indicators?.quote?.[0]?.close)throw Error("missing candle data");
      const closes=x.indicators.quote[0].close as (number|null)[];
      const bars=(x.timestamp as number[]).map((t,i)=>({date:new Date(t*1000).toISOString().slice(0,10),close:closes[i]}))
        .filter((x):x is Candle=>typeof x.close==="number"&&Number.isFinite(x.close)&&x.close>0);
      const unique=[...new Map(bars.map(b=>[b.date,b])).values()].sort((a,b)=>a.date.localeCompare(b.date));
      series[id]=unique;
      return assess(id,name,symbol,unique,x.meta?.currency||"");
    }catch(e){errors.push(`${name}: ${e instanceof Error?e.message:"data unavailable"}`);return assess(id,name,symbol,[]);}
  }));
  return {cards,anomalies:detectAnomalies(cards,series),errors,asOf:new Date().toISOString()};
}
