import sys; sys.path.insert(0, "backtest")  # run from repo root: python backtest/variants.py XAU/USD
import sys, statistics as st
from engine import *
import engine
engine.FUND_PER_NIGHT=0.00015
def to4h(b):
    out=[];cur=None
    for x in b:
        k=(x['t'].date(),x['t'].hour//4)
        if cur and cur['k']==k: cur['h']=max(cur['h'],x['h']);cur['l']=min(cur['l'],x['l']);cur['c']=x['c']
        else:
            cur={'k':k,'t':x['t'].replace(hour=k[1]*4),'o':x['o'],'h':x['h'],'l':x['l'],'c':x['c']};out.append(cur)
    return out
def trend_only(c):
    p=c[-1];e20,e50=alert.ema(c,20)[-1],alert.ema(c,50)[-1];h=alert.macd_hist(c)
    s=(1 if e20>e50 else -1)+(1 if p>e50 else -1)+(1 if h[-1]>0 else -1)
    return "BUY" if s==3 else "SELL" if s==-3 else "WAIT"
def donch(c):
    # close breaks 20-bar high -> BUY; breaks 10-bar low -> SELL
    if c[-1]>max(c[-21:-1]): return "BUY"
    if c[-1]<min(c[-11:-1]): return "SELL"
    return "WAIT"
def ema_trend(c):
    e=alert.ema(c,50)[-1]; e2=alert.ema(c,150)[-1]
    return "BUY" if c[-1]>e>e2 else "SELL" if c[-1]<e<e2 else "WAIT"
def eq(tr):
    e=1;pk=1;dd=0
    for t in sorted(tr,key=lambda t:t['t']): e*=1+0.01*t['R'];pk=max(pk,e);dd=max(dd,1-e/pk)
    return 100*(e-1),100*dd
def test(name,sym,bars,scorer,long_only,stop,tgt,mid):
    sg=signals(bars,scorer); tr=run(sym,bars,sg,stop_atr=stop,target_atr=tgt,long_only=long_only,time_filter=False)
    s=stats(tr); a=stats([t for t in tr if t['t']<mid]); b=stats([t for t in tr if t['t']>=mid])
    r=[stats(run(sym,bars,sg,stop_atr=stop,target_atr=tgt,long_only=long_only,time_filter=False,random_dir=k))['avgR'] for k in range(100)]
    beat=100*sum(x<s['avgR'] for x in r)/len(r); ret,dd=eq(tr)
    print(f"{name:36s} n{s['n']:4d} win{s['win%']:3.0f}% avgR {s['avgR']:+.3f} (OLD 22-25 {a.get('avgR',0):+.2f} NEW 25-26 {b.get('avgR',0):+.2f}) ret {ret:+5.0f}% DD {dd:3.0f}% beats-random {beat:3.0f}%")
from datetime import datetime
for sym in sys.argv[1:]:
    b1=load(sym); b4=to4h(b1); mid=datetime(2025,8,6)
    print(f"== {sym} {b1[0]['t']:%Y-%m-%d} -> {b1[-1]['t']:%Y-%m-%d}  buy&hold {100*(b1[-1]['c']/b1[WINDOW*4]['c']-1):+.0f}%")
    lo = sym=="XAU/USD"
    test("1h bot rules (current)",sym,b1,None,False,1.5,3,mid)
    test("4h bot rules",sym,b4,None,False,1.5,3,mid)
    test("4h bot rules, buy-only",sym,b4,None,True,1.5,3,mid)
    test("4h trend-only, buy-only, 2/4 ATR",sym,b4,trend_only,True,2,4,mid)
    test("4h trend-only, both, 2/4 ATR",sym,b4,trend_only,False,2,4,mid)
    test("4h 50/150 EMA trend, buy-only, 3/9",sym,b4,ema_trend,True,3,9,mid)
    test("4h breakout 20/10, buy-only, 3/9",sym,b4,donch,True,3,9,mid)
    test("4h breakout 20/10, both, 3/9",sym,b4,donch,False,3,9,mid)
