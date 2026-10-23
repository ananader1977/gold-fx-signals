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
