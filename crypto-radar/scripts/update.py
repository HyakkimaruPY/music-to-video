#!/usr/bin/env python3
import json, math, os, re, statistics, time, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs' / 'data'
PROJECTS = json.loads((DATA / 'projects.json').read_text(encoding='utf-8'))
STATE_FILE = Path(os.environ.get('MODEL_STATE_FILE', str(DATA / 'model_state.json')))
LATEST_FILE = DATA / 'latest.json'
CG_BASE = 'https://api.coingecko.com/api/v3'
GDELT = 'https://api.gdeltproject.org/api/v2/doc/doc'
UA = 'crypto-event-radar/0.2 (+github-pages educational research)'
HORIZONS = [1, 3, 6, 12, 24]

TOPIC_RULES = {
    'regulation': ['regulation','regulatory','sec ','securities','lawsuit','ban ','compliance','license','licence','court','legal'],
    'macro_rates': ['interest rate','rates ','fed ','fomc','inflation','cpi','central bank','monetary policy','yield'],
    'risk_geopolitics': ['war ','sanction','conflict','attack','tariff','geopolit','military'],
    'security': ['hack','hacked','exploit','breach','vulnerability','stolen','drain','attack'],
    'listing_liquidity': ['listing','listed','delist','exchange','binance','coinbase','kraken','bybit','upbit','liquidity'],
    'adoption_partnership': ['partnership','partner','integration','integrates','adoption','institution','launches on','collaboration'],
    'product_mainnet': ['mainnet','testnet','upgrade','release','roadmap','feature','protocol launch','genesis'],
    'tokenomics_unlock': ['unlock','vesting','airdrop','tokenomics','supply','emission','burn','staking reward'],
    'rwa_payments': ['rwa','real world asset','payment','payfi','stablecoin','settlement','invoice','credit'],
    'ai_compute': ['artificial intelligence',' ai ','compute','dataset','data marketplace','model training'],
    'oracle_data': ['oracle','price feed','market data','data provider'],
    'interoperability': ['bridge','cross-chain','cross chain','interoperability','multichain','multi-chain'],
}

POSITIVE = {'growth','grows','adoption','approved','approval','launch','launched','partnership','integrates','integration','upgrade','record','expands','expansion','profit','surge','rally','gain','wins','secured','funding','mainnet','milestone'}
NEGATIVE = {'hack','hacked','exploit','lawsuit','ban','banned','outage','loss','losses','drop','falls','fall','decline','delist','delisted','attack','breach','investigation','delay','delayed','risk','warning','sanction'}


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')


def http_json(url, timeout=25, retries=3):
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last = e
            time.sleep(1.5 * (2 ** i))
    raise last


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))

def liquidity_quality(turnover):
    base=clamp(turnover/0.15)
    if turnover<=0.60: return base
    return base*clamp(1-(turnover-0.60)/1.80,0.25,1.0)


def median(xs, default=0.0):
    xs = [x for x in xs if isinstance(x, (int,float)) and math.isfinite(x)]
    return statistics.median(xs) if xs else default


def quantile(xs, q):
    xs = sorted(x for x in xs if isinstance(x,(int,float)) and math.isfinite(x))
    if not xs: return 0.0
    if len(xs)==1: return xs[0]
    p = (len(xs)-1)*q
    i = int(math.floor(p)); j = int(math.ceil(p))
    if i==j: return xs[i]
    return xs[i]*(j-p)+xs[j]*(p-i)


def parse_gdelt_time(s):
    if not s: return None
    s = str(s)
    for fmt in ('%Y%m%dT%H%M%SZ','%Y%m%d%H%M%S','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%d %H:%M:%S'):
        try: return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError: pass
    return None


def sentiment(text):
    toks = re.findall(r"[a-zA-Z][a-zA-Z\-']+", text.lower())
    if not toks: return 0.0
    p = sum(t in POSITIVE for t in toks); n = sum(t in NEGATIVE for t in toks)
    return (p-n) / max(3, p+n)


def topics(text):
    low = ' ' + text.lower() + ' '
    out = []
    for topic, needles in TOPIC_RULES.items():
        if any(n in low for n in needles): out.append(topic)
    return out or ['general']


def event_id(article, coin_id):
    raw = f"{coin_id}|{article.get('url','')}|{article.get('title','')}"
    return hashlib.sha1(raw.encode('utf-8','ignore')).hexdigest()[:20]


def cg_url(path, **params):
    return CG_BASE + path + ('?' + urlencode(params) if params else '')


def fetch_markets(ids=None, page=1):
    params = dict(vs_currency='brl', order='market_cap_desc', per_page=250, page=page, sparkline='false', price_change_percentage='1h,24h,7d')
    if ids: params['ids'] = ','.join(ids)
    return http_json(cg_url('/coins/markets', **params))

def discovery_scan(markets, curated_ids):
    rows=[]
    stable_symbols={'USDT','USDC','DAI','FDUSD','USDE','USDS','TUSD','PYUSD','USD1','USDF'}
    for m in markets:
        price=m.get('current_price'); cap=m.get('market_cap') or 0; vol=m.get('total_volume') or 0
        sym=(m.get('symbol') or '').upper()
        if m.get('id') in curated_ids or sym in stable_symbols or price is None or price>=2 or cap<10_000_000 or vol<1_000_000: continue
        turnover=vol/max(cap,1)
        ch=abs(m.get('price_change_percentage_24h_in_currency') or 0)
        score=100*(0.45*liquidity_quality(turnover)+0.25*clamp(math.log10(cap/10_000_000+1)/2)+0.15*clamp(ch/12)+0.15*clamp(1-(m.get('market_cap_rank') or 500)/500))
        rows.append({'id':m.get('id'),'symbol':sym,'name':m.get('name'),'price_brl':price,'market_cap_brl':cap,'volume_24h_brl':vol,'change_24h_pct':m.get('price_change_percentage_24h_in_currency'),'market_cap_rank':m.get('market_cap_rank'),'discovery_score':round(score,1),'note':'Descoberta quantitativa; propósito/equipe ainda precisam de validação antes de entrar na watchlist.'})
    return sorted(rows,key=lambda x:x['discovery_score'],reverse=True)[:40]


def fetch_chart(coin_id, days=30):
    return http_json(cg_url(f'/coins/{coin_id}/market_chart', vs_currency='brl', days=days))


def to_series(chart):
    prices = [(int(t), float(v)) for t,v in chart.get('prices',[]) if v is not None]
    vols = [(int(t), float(v)) for t,v in chart.get('total_volumes',[]) if v is not None]
    return prices, vols


def nearest_value(series, ts_ms):
    if not series: return None
    return min(series, key=lambda x: abs(x[0]-ts_ms))[1]


def future_value(series, ts_ms, hours):
    target = ts_ms + hours*3600*1000
    candidates = [x for x in series if x[0] >= target]
    return candidates[0][1] if candidates else None


def slice_future(series, ts_ms, hours=24):
    end = ts_ms + hours*3600*1000
    return [(t,v) for t,v in series if ts_ms <= t <= end]


def daily_series(prices):
    by_day = {}
    for t,v in prices:
        d = datetime.fromtimestamp(t/1000, tz=timezone.utc).date().isoformat()
        by_day[d] = v
    return sorted(by_day.items())


def market_stats(prices, vols):
    if len(prices) < 10: return {}
    cutoff = prices[-1][0] - 15*86400*1000
    p15 = [(t,v) for t,v in prices if t >= cutoff]
    d = daily_series(p15)
    vals = [v for _,v in d]
    rets = [(vals[i]/vals[i-1]-1) for i in range(1,len(vals)) if vals[i-1] > 0]
    pos = [r for r in rets if r>0]; neg=[r for r in rets if r<0]
    hourly = [prices[i][1]/prices[i-1][1]-1 for i in range(1,len(prices)) if prices[i-1][1]>0 and prices[i][0]>=cutoff]
    start = p15[0][1]; end = p15[-1][1]
    peak = start; max_dd=0
    for _,v in p15:
        peak=max(peak,v); max_dd=min(max_dd, v/peak-1)
    stable_low, stable_high = quantile(vals,0.25), quantile(vals,0.75)
    vol_vals=[v for t,v in vols if t>=cutoff]
    return {
        'gap_15d_pct': (end/start-1)*100 if start else None,
        'mean_15d': statistics.fmean(vals) if vals else None,
        'median_15d': median(vals),
        'stable_band_q1': stable_low,
        'stable_band_q3': stable_high,
        'typical_up_day_pct': median(pos)*100,
        'typical_down_day_pct': median(neg)*100,
        'positive_day_ratio': (len(pos)/len(rets)) if rets else None,
        'daily_volatility_pct': (statistics.pstdev(rets)*100) if len(rets)>1 else 0,
        'median_abs_hourly_pct': median([abs(x) for x in hourly])*100,
        'max_drawdown_15d_pct': max_dd*100,
        'median_volume_15d': median(vol_vals),
        'start_15d': start,
        'end_15d': end,
    }


def fetch_gdelt(query, timespan='30d', maxrecords=100):
    params = {'query': query,'mode': 'artlist','maxrecords': maxrecords,'format': 'json','sort': 'datedesc','timespan': timespan}
    return http_json(GDELT + '?' + urlencode(params), timeout=35, retries=2).get('articles', [])


def event_features(article, project, prices, vols, btc_prices):
    dt = parse_gdelt_time(article.get('seendate'))
    if not dt: return None
    title = article.get('title') or ''
    ts = int(dt.timestamp()*1000)
    p0 = nearest_value(prices, ts)
    if not p0 or p0<=0: return None
    returns = {}; btc_returns = {}
    for h in HORIZONS:
        ph = future_value(prices, ts, h)
        returns[str(h)] = ((ph/p0)-1)*100 if ph else None
        b0 = nearest_value(btc_prices, ts); bh = future_value(btc_prices, ts, h)
        btc_returns[str(h)] = ((bh/b0)-1)*100 if b0 and bh else None
    fut = slice_future(prices, ts, 24)
    fut_returns = [((v/p0)-1)*100 for _,v in fut]
    max_up = max(fut_returns) if fut_returns else 0
    max_down = min(fut_returns) if fut_returns else 0
    hist_before = [(t,v) for t,v in prices if ts-48*3600*1000 <= t < ts]
    hr = [hist_before[i][1]/hist_before[i-1][1]-1 for i in range(1,len(hist_before)) if hist_before[i-1][1]>0]
    trigger = max(1.0, 1.5 * median([abs(x) for x in hr]) * 100)
    delay = None; direction = 0
    for t,v in fut:
        r=(v/p0-1)*100
        if abs(r)>=trigger:
            delay=max(0,(t-ts)/60000); direction=1 if r>0 else -1; break
    duration = None
    if direction and fut:
        peak_mag=0; peak_i=0
        for i,(t,v) in enumerate(fut):
            r=(v/p0-1)*100*direction
            if r>peak_mag: peak_mag=r; peak_i=i
        for t,v in fut[peak_i+1:]:
            aligned=(v/p0-1)*100*direction
            if aligned <= peak_mag*0.4 or aligned < 0:
                duration=max(0,(t-fut[peak_i][0])/3600000); break
        if duration is None and peak_i < len(fut): duration=(fut[-1][0]-fut[peak_i][0])/3600000
    vol_at = nearest_value(vols, ts)
    prior_vols=[v for t,v in vols if ts-24*3600*1000<=t<ts]
    vol_anom=(vol_at/median(prior_vols,1.0)) if vol_at and prior_vols else 1.0
    r6=returns.get('6'); b6=btc_returns.get('6')
    abnormal=(r6-b6) if r6 is not None and b6 is not None else r6
    tps=topics(title); sent=sentiment(title)
    entity_match = 1.0 if any(term.lower() in title.lower() for term in [project['name'], project['symbol']] + project.get('query_terms',[])) else 0.45
    confidence = clamp(0.25*entity_match + 0.2*clamp(abs(sent)) + 0.25*clamp((vol_anom-1)/2) + 0.30*clamp(abs(abnormal or 0)/5))
    return {
        'id': event_id(article, project['id']),'coin_id': project['id'], 'symbol': project['symbol'], 'name': project['name'],
        'published_at': dt.isoformat().replace('+00:00','Z'),'title': title,'url': article.get('url'), 'domain': article.get('domain'), 'source_country': article.get('sourcecountry'),
        'topics': tps, 'sentiment': sent, 'price_at_event_brl': p0,'returns_pct': returns, 'btc_returns_pct': btc_returns, 'abnormal_6h_pct': abnormal,
        'max_up_24h_pct': max_up, 'max_down_24h_pct': max_down,'reaction_delay_min': delay, 'reaction_duration_h': duration,
        'volume_anomaly': vol_anom, 'association_confidence': confidence,
    }


def update_topic_stats(state, labeled_events):
    stats=state.setdefault('topic_stats',{})
    for ev in labeled_events:
        for topic in ev.get('topics',['general']):
            for scope in (f"coin:{ev['coin_id']}:{topic}", f"global:{topic}"):
                s=stats.setdefault(scope,{})
                for h in HORIZONS:
                    r=ev.get('returns_pct',{}).get(str(h))
                    if r is None: continue
                    hs=s.setdefault(str(h),{'n':0,'sum':0.0,'sum2':0.0,'up':0,'down':0})
                    hs['n']+=1; hs['sum']+=r; hs['sum2']+=r*r
                    hs['up']+= int(r>0); hs['down']+=int(r<0)


def stat_summary(raw):
    n=raw.get('n',0)
    if not n: return {'n':0,'mean':0,'std':0,'p_up':0.5}
    mean=raw['sum']/n
    var=max(0,raw['sum2']/n-mean*mean)
    return {'n':n,'mean':mean,'std':math.sqrt(var),'p_up':(raw.get('up',0)+1)/(n+2)}


def predict_event(ev, state, horizon=6):
    pieces=[]
    for topic in ev.get('topics',['general']):
        for scope,weight in ((f"coin:{ev['coin_id']}:{topic}",1.0),(f"global:{topic}",0.45)):
            raw=state.get('topic_stats',{}).get(scope,{}).get(str(horizon),{})
            sm=stat_summary(raw)
            if sm['n']:
                reliability=sm['n']/(sm['n']+8)
                pieces.append((sm,weight*reliability))
    if not pieces:
        return {'expected_pct':0.0,'p_up':0.5,'std_pct':0.0,'samples':0,'confidence':0.05}
    wsum=sum(w for _,w in pieces) or 1
    mean=sum(s['mean']*w for s,w in pieces)/wsum
    p_up=sum(s['p_up']*w for s,w in pieces)/wsum
    std=sum(max(0.5,s['std'])*w for s,w in pieces)/wsum
    samples=max(s['n'] for s,_ in pieces)
    confidence=clamp((samples/(samples+12))*ev.get('association_confidence',0.5))
    return {'expected_pct':mean,'p_up':p_up,'std_pct':std,'samples':samples,'confidence':confidence}


def technical_score(stats, market):
    if not stats: return 0
    vol=max(0,stats.get('daily_volatility_pct',0)); dd=abs(min(0,stats.get('max_drawdown_15d_pct',0)))
    liq=(market.get('total_volume') or 0)/max(1,(market.get('market_cap') or 1))
    return 100*(0.35*liquidity_quality(liq)+0.30*clamp(1-dd/35)+0.20*clamp(1-abs(vol-4)/10)+0.15*clamp((stats.get('positive_day_ratio') or .5)))


def project_score(project, market, stats):
    market_cap=market.get('market_cap') or 0; liq=(market.get('total_volume') or 0)/max(1,market_cap); age_years=1.5
    try:
        launch=str(project.get('launch','')); dt=datetime.fromisoformat(launch if len(launch)>7 else launch+'-01').replace(tzinfo=timezone.utc)
        age_years=max(0,(datetime.now(timezone.utc)-dt).days/365.25)
    except Exception: pass
    age_score=clamp(1-abs(age_years-1.8)/3.5); mcap_score=clamp(math.log10(max(market_cap,1)/5e6+1)/2.2); liq_score=liquidity_quality(liq); tech=technical_score(stats,market)/100
    return round(100*(0.34*(project.get('purpose_score',75)/100)+0.16*age_score+0.18*liq_score+0.12*mcap_score+0.20*tech),1)


def entry_score(stats, market, news_bias):
    if not stats: return 0
    p=market.get('current_price') or stats.get('end_15d') or 0; q1=stats.get('stable_band_q1') or p; q3=stats.get('stable_band_q3') or p
    position=clamp((q3-p)/(q3-q1)) if q3>q1 else .5
    dd=abs(min(0,stats.get('max_drawdown_15d_pct',0))); stretch=abs(stats.get('gap_15d_pct') or 0)
    return round(100*(0.30*position+0.20*clamp(1-dd/30)+0.20*clamp(1-stretch/35)+0.30*clamp(0.5+news_bias/10)),1)


def main():
    DATA.mkdir(parents=True, exist_ok=True); STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try: state=json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except Exception: state={'version':1,'seen_event_ids':[],'topic_stats':{},'event_history':[]}
    seen=set(state.get('seen_event_ids',[])); trained=set(state.get('trained_event_ids',[])); ids=[p['id'] for p in PROJECTS]
    markets=fetch_markets(ids); by_id={m['id']:m for m in markets}
    try:
        scan_markets=fetch_markets(None,1); scanner=discovery_scan(scan_markets,set(ids))
    except Exception as e:
        print('scanner failed',e); scanner=[]
    charts={}
    for cid in ids+['bitcoin']:
        try: charts[cid]=to_series(fetch_chart(cid,30))
        except Exception as e:
            print('chart failed',cid,e); charts[cid]=([],[])
        time.sleep(0.55)
    btc_prices=charts['bitcoin'][0]

    new_events=[]
    for p in PROJECTS:
        prices,vols=charts[p['id']]
        if not prices: continue
        q=' OR '.join('"'+x+'"' if ' ' in x else x for x in p.get('query_terms',[p['name']]))
        try: arts=fetch_gdelt(q,timespan='30d',maxrecords=120)
        except Exception as e:
            print('gdelt failed',p['id'],e); arts=[]
        for a in arts:
            ev=event_features(a,p,prices,vols,btc_prices)
            if ev and ev['id'] not in seen:
                new_events.append(ev); seen.add(ev['id'])
        time.sleep(0.35)

    hist=state.get('event_history',[])+new_events; cutoff_labeled=datetime.now(timezone.utc)-timedelta(hours=25); labeled=[]
    for ev in hist:
        dt=datetime.fromisoformat(ev['published_at'].replace('Z','+00:00'))
        if ev.get('id') not in trained and dt <= cutoff_labeled and ev.get('returns_pct',{}).get('24') is not None:
            labeled.append(ev); trained.add(ev.get('id'))
    update_topic_stats(state,labeled)

    hist=sorted(hist,key=lambda e:e.get('published_at',''), reverse=True)[:1500]
    state['event_history']=hist; state['seen_event_ids']=list(seen)[-5000:]; state['trained_event_ids']=list(trained)[-5000:]; state['updated_at']=now_iso()

    current_events=[]; alerts=[]; market_rows=[]; fresh_cut=datetime.now(timezone.utc)-timedelta(hours=12)
    for p in PROJECTS:
        m=by_id.get(p['id'],{}); prices,vols=charts[p['id']]; st=market_stats(prices,vols); pevs=[]
        for ev in hist:
            if ev.get('coin_id')!=p['id']: continue
            dt=datetime.fromisoformat(ev['published_at'].replace('Z','+00:00'))
            if dt>=fresh_cut:
                pred6=predict_event(ev,state,6); pred24=predict_event(ev,state,24); e=dict(ev); e['prediction_6h']=pred6; e['prediction_24h']=pred24
                pevs.append(e); current_events.append(e)
        biases=[]
        for e in pevs:
            pr=e['prediction_6h']; age=(datetime.now(timezone.utc)-datetime.fromisoformat(e['published_at'].replace('Z','+00:00'))).total_seconds()/3600; decay=math.exp(-age/8)
            biases.append(pr['expected_pct']*pr['confidence']*decay)
            if pr['samples']>=4 and pr['confidence']>=0.28 and (pr['p_up']>=0.67 or pr['p_up']<=0.33) and abs(pr['expected_pct'])>=1.0:
                alerts.append({'coin_id':p['id'],'symbol':p['symbol'],'name':p['name'],'event_id':e['id'],'title':e['title'],'published_at':e['published_at'],'direction':'up' if pr['p_up']>=.67 else 'down','probability':max(pr['p_up'],1-pr['p_up']),'expected_6h_pct':pr['expected_pct'],'range_low_pct':pr['expected_pct']-1.28*pr['std_pct'],'range_high_pct':pr['expected_pct']+1.28*pr['std_pct'],'confidence':pr['confidence'],'samples':pr['samples'],'topics':e['topics'],'reason':'Evento recente semelhante a padrões historicamente associados a movimentos subsequentes.'})
        nb=sum(biases) if biases else 0; pscore=project_score(p,m,st); escore=entry_score(st,m,nb)
        market_rows.append({'id':p['id'],'symbol':p['symbol'],'name':p['name'],'organization':p['organization'],'launch':p['launch'],'purpose':p['purpose'],'category':p['category'],'current_price_brl':m.get('current_price'),'market_cap_brl':m.get('market_cap'),'volume_24h_brl':m.get('total_volume'),'change_1h_pct':m.get('price_change_percentage_1h_in_currency'),'change_24h_pct':m.get('price_change_percentage_24h_in_currency'),'change_7d_pct':m.get('price_change_percentage_7d_in_currency'),'stats_15d':st,'project_score':pscore,'entry_score':escore,'news_bias_6h_pct':nb,'source_urls':p.get('sources',[])})

    latest={'generated_at':now_iso(),'status':'ok','source_status':{'coingecko':'ok','gdelt':'ok' if new_events else 'no-new-events-or-unavailable'},'methodology':{'price_filter_brl':2.0,'horizons_h':HORIZONS,'causality_note':'Eventos são associados temporalmente a reações; o sistema não afirma causalidade.','alert_rule':'Exige amostra histórica, confiança mínima e efeito esperado relevante.'},'market':sorted(market_rows,key=lambda x:(x['project_score'],x['entry_score']),reverse=True),'scanner':scanner,'events':sorted(current_events,key=lambda e:e['published_at'],reverse=True)[:80],'alerts':sorted(alerts,key=lambda a:a['confidence']*a['probability'], reverse=True)[:30],'model':{'sample_count':sum(v2.get('n',0) for s in state.get('topic_stats',{}).values() for v2 in s.values()),'topic_keys':len(state.get('topic_stats',{}))}}
    STATE_FILE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8'); LATEST_FILE.write_text(json.dumps(latest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'generated_at':latest['generated_at'],'coins':len(market_rows),'new_events':len(new_events),'labeled':len(labeled),'alerts':len(alerts)},ensure_ascii=False))

if __name__=='__main__':
    main()
