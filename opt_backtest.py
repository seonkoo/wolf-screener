# -*- coding: utf-8 -*-
"""
小狼策略 · 参数化回测沙盒（优化用）
忠实复刻 auto_screener.py 的 贪婪指数 / 日线代理技术共振 逻辑，
对历史日K线切片，测试不同 持有期 / 止损止盈 / 贪婪阈值 / 好公司质量叠加 变体，
并用「同期全市场均值」作为公平基准(避免用大盘蓝筹 HS300 误判小盘恐慌股)。

K线本地缓存(klines_cache.json)避免重复抓取；基本面 as-of 防未来函数。
用法：python opt_backtest.py [pool_cap=1500] [--refresh]
"""
import urllib.request, json, ssl, math, sys, time, os, random, concurrent.futures, threading

def clean_nan(o):
    """递归把 NaN/Infinity 换成 None，避免写出浏览器解析不了的 NaN（非法 JSON）。"""
    if isinstance(o, float):
        return o if (o == o and o != float('inf') and o != float('-inf')) else None
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_nan(v) for v in o]
    return o
import datetime as _dt

CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
HDR = {'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'}
def get(u):
    req = urllib.request.Request(u, headers=HDR)
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8','ignore')

# ---------------- 指标（与 auto_screener.py 一致） ----------------
def calc_ema(data, period):
    k = 2/(period+1); ema=[data[0]]
    for i in range(1,len(data)): ema.append(data[i]*k + ema[-1]*(1-k))
    return ema
def calc_macd(closes):
    if len(closes) < 30: return None
    e12=calc_ema(closes,12); e26=calc_ema(closes,26)
    dif=[e12[i]-e26[i] for i in range(len(closes))]
    dea=calc_ema(dif,9); macd=[(dif[i]-dea[i])*2 for i in range(len(closes))]
    return {'dif':dif,'dea':dea,'macd':macd}
def check_macd_divergence(closes,dif):
    if len(closes)<20 or len(dif)<20: return False
    n=len(closes); low1=-1; low2=-1; look=min(n,60)
    for i in range(n-look,n):
        if 0<i<n-1 and closes[i]<closes[i-1] and closes[i]<closes[i+1]:
            if low2==-1: low2=i
            elif low1==-1 and i<low2-3: low1=i
    if low1>=0 and low2>=0:
        if closes[low2]<closes[low1] and dif[low2]>dif[low1]: return True
    return False
def calc_bollinger(closes, period=20, mult=2):
    if len(closes)<period: return None
    n=len(closes); sma=[];up=[];lo=[]
    for i in range(period-1,n):
        sl=closes[i-period+1:i+1]; mean=sum(sl)/period
        std=(sum((b-mean)**2 for b in sl)/period)**0.5
        sma.append(mean);up.append(mean+mult*std);lo.append(mean-mult*std)
    li=len(sma)-1; price=closes[n-1]
    pos='下轨支撑' if price<=lo[li] else '中轨附近' if price<=sma[li] else '上轨突破' if price>=up[li] else '中上轨间'
    return {'mid':sma[li],'upper':up[li],'lower':lo[li],'price':price,'position':pos}
def calc_greed(closes):
    if len(closes)<30: return 50.0
    cur=closes[-1]; look=min(len(closes)-1,750); hist=closes[-look-1:-1]
    if not hist: return 50.0
    below=sum(1 for c in hist if c<cur)
    return round(below/len(hist)*1000)/10

# ---------------- 数据获取 ----------------
def fetch_kline(code, n=750):
    tcode=('sh' if code[0] in '69' else 'sz')+code
    varn='k'+code+'_'+str(random.randint(0,999999))
    url='https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=%s,day,,,%d'%(varn,tcode,n)
    for _ in range(3):
        try:
            raw=get(url); raw=raw[raw.index('=')+1:]
            d=json.loads(raw); kd=d.get('data',{}).get(tcode,{})
            kl=kd.get('day') or kd.get('qfqday')
            if not kl: return []
            return [{'date':k[0],'open':float(k[1]),'close':float(k[2]),'high':float(k[3]),'low':float(k[4]),'volume':float(k[5]) if len(k)>5 else 0} for k in kl]
        except Exception:
            time.sleep(0.15)
    return []

def get_codes(cap=1500):
    import akshare as ak
    codes=[]
    try:
        sh=ak.stock_info_sh_name_code(); sz=ak.stock_info_sz_name_code()
        def norm(df):
            cols=list(df.columns)
            cc='code' if 'code' in cols else ('symbol' if 'symbol' in cols else cols[0])
            nc='name' if 'name' in cols else cols[1]
            return [(str(r[cc]), str(r[nc])) for _,r in df.iterrows()]
        codes=norm(sh)+norm(sz)
    except Exception as e:
        print('  akshare列表失败:',e); codes=[]
    if len(codes)<200:
        try:
            df=ak.stock_zh_a_spot_em()
            codes=[(str(r['代码']),str(r['名称'])) for _,r in df.iterrows()]
        except Exception as e: print('  spot回退失败:',e)
    out=[]
    for c,n in codes:
        if not c or len(c)<6: continue
        if c[0][0] not in '603': continue          # 仅沪(6)/深(0,3)主板，排除北交所(8)/三板(4)/B股
        if c.startswith('688'): continue           # 排除科创板
        if 'ST' in n or '退' in n: continue
        out.append((c,n))
    seen=set(); uniq=[]
    for c,n in out:
        if c in seen: continue
        seen.add(c); uniq.append((c,n))
    return uniq[:cap]

CACHE='klines_cache.json'
def load_klines(pool, refresh=False):
    if not refresh and os.path.exists(CACHE):
        try:
            d=json.load(open(CACHE,encoding='utf-8')); print('  载入缓存 %d 只'%len(d)); return d
        except Exception: pass
    kd={}
    def w(c):
        try: return c, fetch_kline(c)
        except Exception: return c, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs=[ex.submit(w,c) for c,_ in pool]
        done=0
        for f in concurrent.futures.as_completed(futs):
            c,kl=f.result(); kd[c]=kl; done+=1
            if done%100==0: print('  K线抓取 %d/%d'%(done,len(pool)))
    json.dump(clean_nan(kd), open(CACHE,'w',encoding='utf-8'), allow_nan=False)
    print('  缓存写入 %d 只 -> %s'%(len(kd),CACHE)); return kd

# ---------------- 信号 / 收益 ----------------
def compute_signal(kd, idx, greed_th, tech_th):
    """在 kd[:idx+1] 上计算贪婪指数与技术共振，返回 (greed, tech) 或 None。"""
    closes=[k['close'] for k in kd[:idx+1]]
    if len(closes)<30: return None
    greed=calc_greed(closes)
    if greed>=greed_th: return None
    md=calc_macd(closes)
    tech=0
    b=calc_bollinger(closes)
    if b and b['position'] in ('下轨支撑','中轨附近'): tech+=1
    price=closes[-1]; ma20=sum(closes[-20:])/20
    if price>=ma20: tech+=1
    lo=max(0,idx-19); avgvol=sum(kd[i]['volume'] for i in range(lo,idx+1))/max(1,(idx-lo+1))
    lastvol=kd[idx]['volume']
    if avgvol>0 and lastvol>1.5*avgvol: tech+=1
    if md and check_macd_divergence(closes, md['dif']): tech+=1
    if tech<tech_th: return None
    return greed, tech

def forward_return(kd, idx, hold, stop=None, tp=None):
    """从 idx 起持有最多 hold 日，stop/tp 触发则提前离场。返回 (收益, 持有天数, 离场原因)。"""
    entry=kd[idx]['close']
    end=min(idx+hold, len(kd))
    for j in range(idx+1, end):
        ret=kd[j]['close']/entry-1
        if stop is not None and ret<=stop: return ret, j-idx, 'stop'
        if tp is not None and ret>=tp: return ret, j-idx, 'tp'
    if idx+hold < len(kd):
        return kd[idx+hold]['close']/entry-1, hold, 'hold'
    last=len(kd)-1
    return kd[last]['close']/entry-1, last-idx, 'hold'

def build_checkpoints(kd_ref):
    dates=[k['date'] for k in kd_ref]
    cps=[]
    # 至少 260 根历史(贪婪指数稳健)，至少 65 根未来(可测60日持有)
    for i in range(260, len(dates)-65, 12):
        cps.append((i, dates[i]))
    return cps

# ---------------- 好公司 as-of 校验 ----------------
import pandas as pd
YJ_SNAPS={}
FIN_CACHE={}
FUND_LOCK=threading.Lock()
def load_yj_snap(rd):
    if rd in YJ_SNAPS: return YJ_SNAPS[rd]
    import akshare as ak
    try:
        df=ak.stock_yjbb_em(date=rd)
        m={str(r['股票代码']):r for _,r in df.iterrows()}
        print('  业绩报表(%s) 载入 %d 只'%(rd,len(m)))
        YJ_SNAPS[rd]=m; return m
    except Exception as e:
        print('  业绩报表(%s)失败:%s'%(rd,e)); YJ_SNAPS[rd]={}; return {}
def report_date_for(cp_date):
    d=_dt.datetime.strptime(cp_date,'%Y-%m-%d')
    qe=[(3,31),(6,30),(9,30),(12,31)]; cands=[]
    for y in (d.year-1, d.year):
        for m,day in qe:
            c=_dt.datetime(y,m,day)
            if c<=d: cands.append(c)
    return max(cands).strftime('%Y%m%d')
def get_good(code, asof, rd):
    row=YJ_SNAPS.get(rd,{}).get(code)
    grow=False
    if row is not None:
        try:
            rev_yoy=float(row['营业总收入-同比增长'])>0
            np_yoy=float(row['净利润-同比增长'])>0
            grow=rev_yoy and np_yoy
            if rd.endswith('1231'):
                rev_qoq=float(row['营业总收入-季度环比增长'])>0
                np_qoq=float(row['净利润-季度环比增长'])>0
                grow=grow and rev_qoq and np_qoq
        except Exception: grow=False
    roe_ok=ocf_ok=False
    with FUND_LOCK:
        if code not in FIN_CACHE:
            import akshare as ak
            try:
                sy=int(asof[:4])-3
                FIN_CACHE[code]=ak.stock_financial_analysis_indicator(symbol=code, start_year=str(sy))
            except Exception: FIN_CACHE[code]=None
        df=FIN_CACHE[code]
    if df is not None:
        d2=df.copy(); d2['_d']=d2['日期'].astype(str)
        d2=d2[pd.to_datetime(d2['日期'])<=pd.Timestamp(asof[:10])]
        yr=d2[d2['_d'].str.endswith('12-31')].tail(3)
        if len(yr)>=3:
            roe_ok=all(float(x['净资产收益率(%)'])>8 for _,x in yr.iterrows())
            ocf_ok=all(float(x['每股经营性现金流(元)'])>0 for _,x in yr.iterrows())
    return bool(grow) and roe_ok and ocf_ok

# ---------------- 主流程 ----------------
def main():
    cap=int(sys.argv[1]) if len(sys.argv)>1 else 1500
    refresh='--refresh' in sys.argv
    print('[0] 取股票池(沪深主板, cap=%d) ...'%cap)
    pool=get_codes(cap)
    print('    池子 %d 只'%len(pool))
    print('[1] 抓取/载入日K线(750日)...')
    K=load_klines(pool, refresh)
    # 参考日历
    ref=None
    for c,_ in pool:
        if K.get(c): ref=K[c]; break
    cps=build_checkpoints(ref)
    print('    检查点 %d 个 (跨度 %s ~ %s)'%(len(cps), cps[0][1], cps[-1][1]))

    # 基准：每检查点、每持有期 全市场(池内)买入持有均值
    print('[2] 计算公平基准(全市场买入持有均值)...')
    bm={}  # cp -> {hold: mean_ret}
    for cp in cps:
        i,date=cp; bm[cp]={}
        rs=[]
        for c,_ in pool:
            kd=K.get(c)
            if not kd or len(kd)<=i+10: continue
            r,_,_=forward_return(kd,i,40)  # 用40日作为基准窗口代理；各变体按其hold取bm
            rs.append(r)
        for h in (10,20,40,60):
            rr=[]
            for c,_ in pool:
                kd=K.get(c)
                if not kd or len(kd)<=i+h: continue
                rr.append(forward_return(kd,i,h)[0])
            bm[cp][h]= (sum(rr)/len(rr)) if rr else 0.0

    # 预计算：每个检查点、满足最宽松条件(greed<45 & tech>=2)的股票
    print('[3] 预计算信号(最宽松 greed<45 & tech>=2)...')
    pre={}
    for cp in cps:
        i,date=cp; lst=[]
        for c,_ in pool:
            kd=K.get(c)
            if not kd or len(kd)<=i: continue
            r=compute_signal(kd,i,45,2)
            if r: lst.append((c,i,r[0],r[1]))
        pre[cp]=lst
        print('    检查点 %s: 候选信号 %d 只'%(date,len(lst)))

    # 变体定义
    variants=[
        ('V0基(baseline)', dict(greed=35, hold=10, stop=None, tp=None)),
        ('V1止损8止盈15@10', dict(greed=35, hold=10, stop=-0.08, tp=0.15)),
        ('V2止损6止盈12@40', dict(greed=35, hold=40, stop=-0.06, tp=0.12)),
        ('V3止损8止盈15@40', dict(greed=35, hold=40, stop=-0.08, tp=0.15)),
        ('V4止损8止盈20@60', dict(greed=35, hold=60, stop=-0.08, tp=0.20)),
        ('V5g40止损8止盈15@40', dict(greed=40, hold=40, stop=-0.08, tp=0.15)),
        ('V6g45止损8止盈15@40', dict(greed=45, hold=40, stop=-0.08, tp=0.15)),
    ]
    print('[4] 回测各变体...')
    results={}
    for vname,cfg in variants:
        recs=[]  # (ret, reason)
        for cp in cps:
            i,date=cp
            for c,ii,greed,tech in pre[cp]:
                if greed>=cfg['greed']: continue
                kd=K.get(c)
                if not kd: continue
                r,days,reason=forward_return(kd,i,cfg['hold'],cfg['stop'],cfg['tp'])
                recs.append((r,reason))
        rets=[x[0] for x in recs]
        n=len(rets)
        win=sum(1 for x in rets if x>0)
        avg=sum(rets)/n if n else 0
        sret=sorted(rets); med=sret[n//2] if n else 0
        # 超额 vs 基准：逐检查点平均
        excess=[]
        for cp in cps:
            i,date=cp
            crs=[x[0] for (c,ii,greed,tech) in pre[cp] if greed<cfg['greed'] for x in [forward_return(K.get(c),i,cfg['hold'],cfg['stop'],cfg['tp'])]]
            if crs:
                strat=sum(crs)/len(crs)
                base=bm[cp][cfg['hold']]
                excess.append(strat-base)
        avg_ex=sum(excess)/len(excess) if excess else 0
        stop_r=sum(1 for _,rs in recs if rs=='stop')/n if n else 0
        tp_r=sum(1 for _,rs in recs if rs=='tp')/n if n else 0
        results[vname]={'n':n,'win':win/n if n else 0,'avg':avg,'med':med,'excess':avg_ex,'stop_r':stop_r,'tp_r':tp_r}
        print('  %-22s 信号=%4d 胜率=%5.1f%% 均值=%+6.2f%% 中位=%+6.2f%% 超额=%+6.2f%%  止损%.0f%% 止盈%.0f%%'%(vname,n,win/n*100 if n else 0,avg*100,med*100,avg_ex*100,stop_r*100,tp_r*100))

    # 质量叠加：在 V0/V3 信号上做 as-of 好公司校验，比较 good vs 非good
    print('[5] 好公司质量叠加验证(基于 greed<35 & tech>=2 信号)...')
    good_rets=[]; bad_rets=[]
    for cp in cps:
        i,date=cp; rd=report_date_for(date)
        load_yj_snap(rd)
        for c,ii,greed,tech in pre[cp]:
            if greed>=35: continue
            kd=K.get(c)
            if not kd: continue
            r,days,reason=forward_return(kd,i,40,-0.08,0.15)  # 用较优配置测质量
            try:
                g=get_good(c,date,rd)
            except Exception:
                g=False
            (good_rets if g else bad_rets).append(r)
    def stat(xs):
        n=len(xs); 
        return (n, (sum(1 for x in xs if x>0)/n if n else 0), (sum(xs)/n if n else 0), (sorted(xs)[n//2] if n else 0))
    gn,gw,ga,gm=stat(good_rets); bn,bw,ba,bm_=stat(bad_rets)
    print('  好公司: 信号=%d 胜率=%.1f%% 均值=%+.2f%% 中位=%+.2f%%'%(gn,gw*100,ga*100,gm*100))
    print('  非好公司: 信号=%d 胜率=%.1f%% 均值=%+.2f%% 中位=%+.2f%%'%(bn,bw*100,ba*100,bm_*100))

    # 输出
    out={'variants':results,'quality':{'good':{'n':gn,'win':gw,'avg':ga,'med':gm},'bad':{'n':bn,'win':bw,'avg':ba,'med':bm_}}}
    json.dump(clean_nan(out), open('opt_result.json','w',encoding='utf-8'), ensure_ascii=False, indent=1, allow_nan=False)
    print('\n✅ 已保存 opt_result.json')

if __name__=='__main__':
    t0=time.time(); main(); print('耗时 %.1f 分'%((time.time()-t0)/60))
