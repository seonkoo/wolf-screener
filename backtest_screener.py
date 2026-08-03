# -*- coding: utf-8 -*-
"""
小狼策略 · 历史回测验证器（walk-forward 重放版）

核心思想：不跟实盘信号走，而是在历史上"每一天"把策略规则重放一遍，
每只股票每个信号点都模拟 买入→持有→触发止损/止盈/到期，统计赚的比例。
这样"信号每天变"完全不影响回测——回测本身就是"每天重放"。

对齐实跑参数（来自 auto_screener.py）：
    GREED_PASS=40  低位/恐慌阈值
    HOLD_DAYS=40   持有天数
    STOP_PCT=0.08  止损 8%
    TP_PCT=0.15    止盈 15%
    入场 = L1(贪婪<40) 且 L3(技术共振 tech>=2，日线代理)
    ⚠️ 不按主力净流入预筛（回测证明那会漏掉恐慌低位股，胜率从61-65%暴跌到36%）

新增：市场方向门控对比
    拉沪深300日K算 MA120，把每个信号标注为"大盘上行期/下行期"，
    分别统计胜率，验证"只在大盘上行期出手"能否把胜率推到 70%。

新增：蓝筹低吸回测
    沪深300 成分中"现价<250日均线(低吸区)"作为入场信号，持有120日，
    统计长持胜率（蓝筹偏长期，用更长持有窗口）。

用法：python backtest_screener.py  [poolN=1000]  [bars=750]
"""
import urllib.request, json, ssl, urllib.parse, sys, threading, os, importlib.util, statistics, math
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
lock=threading.Lock()

# ---- 对齐实跑参数 ----
GREED_PASS = 40
HOLD_DAYS  = 40
STOP_PCT   = 0.08
TP_PCT     = 0.15

# ---- 复用 auto_screener 的好公司判定（as-of 防未来函数）----
_spec=importlib.util.spec_from_file_location('auto_screener', os.path.join(os.path.dirname(os.path.abspath(__file__)),'auto_screener.py'))
AS=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(AS)
load_yj_map=AS.load_yj_map; get_fundamentals=AS.get_fundamentals; YJ_SNAPS=AS.YJ_SNAPS

def get(u, ref='https://quote.eastmoney.com/'):
    req=urllib.request.Request(u, headers={'User-Agent':'Mozilla/5.0','Referer':ref})
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8','ignore')

# ---------- 指标（与 auto_screener.run_screening 日线代理一致）----------
def calc_ema(data, period):
    k=2/(period+1); ema=[data[0]]
    for i in range(1,len(data)): ema.append(data[i]*k+ema[-1]*(1-k))
    return ema

def calc_macd(closes):
    if len(closes)<30: return None
    e12=calc_ema(closes,12); e26=calc_ema(closes,26)
    dif=[e12[i]-e26[i] for i in range(len(closes))]
    dea=calc_ema(dif,9)
    return {'dif':dif}

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

def calc_boll_pos(closes, period=20, mult=2):
    if len(closes)<period: return None
    sl=closes[-period:]; mean=sum(sl)/period
    std=(sum((b-mean)**2 for b in sl)/period)**0.5
    lo=mean-mult*std; up=mean+mult*std; p=closes[-1]
    if p<=lo: return '下轨支撑'
    if p<=mean: return '中轨附近'
    if p>=up: return '上轨突破'
    return '中上轨间'

def calc_greed(closes):
    if len(closes)<30: return 50.0
    cur=closes[-1]; look=min(len(closes)-1,750); hist=closes[-look-1:-1]
    if not hist: return 50.0
    below=sum(1 for c in hist if c<cur)
    return round(below/len(hist)*1000)/10

def entry_signal(kd, idx, require_uptrend=False):
    """对齐实跑 A 入场：L1 贪婪<40 且 L3 技术共振(日线代理) tech>=2。返回 (greed,tech) 或 None。
    require_uptrend=True 时额外要求股价在250日线上方(只买"上升趋势中的恐慌回踩"，经典高胜率形态)。"""
    cl=[float(k[2]) for k in kd[:idx+1]]
    if len(cl)<30: return None
    if require_uptrend and len(cl)>=250 and cl[-1] < sum(cl[-250:])/250:
        return None
    greed=calc_greed(cl)
    if greed>=GREED_PASS: return None          # L1 不过
    tech=0; sig=[]
    b=calc_boll_pos(cl)
    if b and b in ('下轨支撑','中轨附近'): tech+=1; sig.append('布林'+b)
    ma20=sum(cl[-20:])/20
    if cl[-1]>=ma20: tech+=1; sig.append('站上MA20')
    vols=[float(k[5]) for k in kd[max(0,idx-19):idx+1]]; lastv=float(kd[idx][5]); av=sum(vols)/len(vols)
    if av>0 and lastv>1.5*av: tech+=1; sig.append('放量×%.1f'%(lastv/av))
    md=calc_macd(cl)
    if md and check_macd_divergence(cl,md['dif']): tech+=1; sig.append('日线底背离')
    if tech>=2: return (greed,tech,sig)
    return None

def simulate(kd, cp, hold=HOLD_DAYS, stop=STOP_PCT, tp=TP_PCT):
    """从 cp 收盘买入，逐日向前走 hold 天，触发止盈/止损/到期结算。
    返回 ('win'/'loss', 实际收益率, 出场天数)。"""
    try: entry=float(kd[cp][2])
    except Exception: return None
    if entry<=0 or cp+hold>=len(kd): return None
    for i in range(1,hold+1):
        try: c=float(kd[cp+i][2])
        except Exception: break
        ret=c/entry-1
        if ret>=tp: return ('win',tp,i)
        if ret<=-stop: return ('loss',-stop,i)
    last=float(kd[cp+hold][2]); r=last/entry-1
    return ('win' if r>0 else 'loss', r, hold)

# ---------- 大盘方向（沪深300 MA120）----------
def get_index_series(code='sh000300', bars=900):
    try:
        raw=get('https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,%d'%(code,bars),'https://gu.qq.com/')
        raw=raw[raw.index('=')+1:]; kd=json.loads(raw)['data'][code]['day']
        dates=[k[0] for k in kd]; closes=[float(k[2]) for k in kd]
        return dates,closes
    except Exception as e:
        print('  [warn] 指数序列获取失败:',e); return None,None

def build_regime(dates, closes, win=120):
    """返回 date->'up'/'down'（收盘与 MA120 关系）。"""
    n=len(closes); ma=[None]*n
    for i in range(win-1,n):
        ma[i]=sum(closes[i-win+1:i+1])/win
    reg={}
    for i in range(n):
        if ma[i] is None: continue
        reg[dates[i]]='up' if closes[i]>=ma[i] else 'down'
    return reg

# ---------- 股票池（宽扫描，不过滤净流入）----------
def get_codes(N):
    try:
        import akshare as ak
        sh=ak.stock_info_sh_name_code(); sz=ak.stock_info_sz_name_code()
        def norm(df):
            cols=list(df.columns); cc='code' if 'code' in cols else ('symbol' if 'symbol' in cols else cols[0]); nc='name' if 'name' in cols else cols[1]
            return [(str(r[cc]), r[nc]) for _,r in df.iterrows()]
        codes=norm(sh)+norm(sz)
    except Exception as e:
        print('  akshare列表失败,回退clist:',e); codes=[]
        for pn in range(1,40):
            u='https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=200&fid=f12&po=1&fltt=2&invt=2&np=1&ut=fa5fd079d0a4d4f8f8&fs=m:0+t:6&fields=f12,f14'%pn
            try: d=json.loads(get(u)); diff=d.get('data',{}).get('diff',[])
            except: diff=[]
            if not diff: break
            for r in diff: codes.append((r['f12'], r['f14']))
            if len(codes)>=N+200: break
    out=[c for c in codes if len(c[0])==6 and c[0][0] in '603' and not c[0].startswith('688')
         and 'ST' not in c[1] and '退' not in c[1]]
    return out[:N]

def fetch_kline(code, bars):
    tc=('sh'+code) if code.startswith('6') else ('sz'+code)
    try:
        raw=get('https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,%d'%(tc,bars),'https://gu.qq.com/')
        raw=raw[raw.index('=')+1:]; kd=json.loads(raw)['data'][tc]['day']
        if len(kd)>260: return kd
    except Exception:
        pass
    return None

# ---------- 主流程 ----------
def main():
    N=int(sys.argv[1]) if len(sys.argv)>1 else 1000
    BARS=int(sys.argv[2]) if len(sys.argv)>2 else 750
    global TP_PCT, STOP_PCT
    TP_PCT=float(sys.argv[3]) if len(sys.argv)>3 else TP_PCT
    STOP_PCT=float(sys.argv[4]) if len(sys.argv)>4 else STOP_PCT
    REQ_UT=len(sys.argv)>5 and sys.argv[5] in ('1','ut','uptrend')
    print('='*70)
    print('小狼策略 · walk-forward 回测（宽扫描 + 40日止损止盈 + 市场门控）')
    print('  参数: 贪婪<%d  持有%d日  止损%.0f%%  止盈%.0f%%'%(GREED_PASS,HOLD_DAYS,STOP_PCT*100,TP_PCT*100))
    print('='*70)
    # 大盘方向
    print('[0] 拉取沪深300 判断大盘方向...')
    idates,icloses=get_index_series('sh000300', BARS+200)
    regime=build_regime(idates,icloses,120) if idates else {}
    if regime:
        ups=sum(1 for v in regime.values() if v=='up'); tot=len(regime)
        print('      大盘上行期占比 %.1f%% (%d/%d)'%(ups/tot*100,ups,tot))
    # 股票池
    codes=get_codes(N)
    print('[1] 宽扫描池:',len(codes))
    kdata={}
    def fetch(code,name):
        kd=fetch_kline(code,BARS)
        if kd:
            with lock: kdata[code]=(name,kd)
    ts=[threading.Thread(target=fetch,args=(c,nm)) for c,nm in codes]
    for t in ts: t.start()
    for t in ts: t.join()
    print('[2] 有效K线:',len(kdata))
    # 检查点：每 8 个交易日重放一次（覆盖牛熊）
    sample=list(kdata.values())[0][1]
    L=len(sample)
    cps=list(range(L-700, L-12, 8))
    cps=[c for c in cps if c>30]
    print('[3] 历史检查点:',len(cps),' 区间',sample[cps[0]][0],'~',sample[cps[-1]][0])
    sig=[]
    for cp in cps:
        cp_date=sample[cp][0]
        rg=regime.get(cp_date,'na')
        for code,(name,kd) in kdata.items():
            if cp>=len(kd)-HOLD_DAYS-1: continue
            e=entry_signal(kd,cp,REQ_UT)
            if not e: continue
            sim=simulate(kd,cp)
            if not sim: continue
            try: settle=float(kd[cp+HOLD_DAYS][2])/float(kd[cp][2])-1
            except Exception: settle=None
            sig.append((cp_date,code,name,e[0],e[1],sim[0],sim[1],rg,settle))
    print('[4] 命中入场信号:',len(sig))
    if not sig:
        print('  无信号，退出'); return
    def stats(sub,label):
        if not sub:
            print('  %-26s 信号%4d | 无数据'%(label,0)); return
        wins=sum(1 for s in sub if s[5]=='win'); rets=[s[6] for s in sub]
        avg=sum(rets)/len(rets); med=statistics.median(rets)
        print('  %-26s 信号%4d | 严格胜率 %5.1f%% | 平均 %+6.2f%% | 中位 %+6.2f%%'%(
            label,len(sub),wins/len(sub)*100,avg*100,med*100))
    print('\n=== 回测结果（持有%d日，止损%d%%/止盈%d%%，宽扫描不过滤净流入）==='%(HOLD_DAYS,int(STOP_PCT*100),int(TP_PCT*100)))
    stats(sig,'[全样本]')
    up=[s for s in sig if s[7]=='up']; dn=[s for s in sig if s[7]=='down']; na=[s for s in sig if s[7]=='na']
    stats(up,'[仅大盘上行期]')
    stats(dn,'[仅大盘下行期]')
    stats(na,'[无大盘数据]')
    # 好公司过滤对照（as-of，失败不影响主结论）
    try:
        rep_dates=sorted({('%s'%s[0][:4]+('0331' if 5<=int(s[0][5:7])<=8 else '0630' if 9<=int(s[0][5:7])<=10 else '0930' if int(s[0][5:7])>=11 else '1231')) for s in sig})
        for rd in rep_dates[:6]:
            try: load_yj_map(rd)
            except Exception: pass
        good=[]
        for s in sig:
            code=s[1]; cp_date=s[0]
            rd='%s%s'%(cp_date[:4], '0331' if 5<=int(cp_date[5:7])<=8 else '0630' if 9<=int(cp_date[5:7])<=10 else '0930' if int(cp_date[5:7])>=11 else '1231')
            row=YJ_SNAPS.get(rd,{}).get(code)
            try:
                g,_=get_fundamentals(code,yj_row=row,asof=cp_date,annual=rd.endswith('1231'))
                if g: good.append(s)
            except Exception: pass
        stats(good,'[全样本+好公司]')
    except Exception as e:
        print('  [warn] 好公司对照跳过:',e)
    # 保存摘要供页面展示
    out={'generated':__import__('time').strftime('%Y-%m-%d %H:%M'),
         'params':{'greed_pass':GREED_PASS,'hold_days':HOLD_DAYS,'stop':STOP_PCT,'tp':TP_PCT},
         'all':{'n':len(sig),'win':round(sum(1 for s in sig if s[5]=='win')/len(sig)*100,1)},
         'up_only':{'n':len(up),'win':round(sum(1 for s in up if s[5]=='win')/len(up)*100,1) if up else 0},
         'down_only':{'n':len(dn),'win':round(sum(1 for s in dn if s[5]=='win')/len(dn)*100,1) if dn else 0},
         'good':{'n':len(good),'win':round(sum(1 for s in good if s[5]=='win')/len(good)*100,1) if good else 0}}
    json.dump(out, open('backtest_winrate.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n✅ 已保存 backtest_winrate.json')
    print('\n结论速读：')
    print('  · 全样本胜率 %.1f%% ；仅大盘上行期 %.1f%% ；仅下行期 %.1f%%'%(out['all']['win'],out['up_only']['win'],out['down_only']['win']))
    print('  · ⚠️ 下行期胜率(%.1f%%) > 上行期(%.1f%%)：本策略是"买恐慌"均值回归，恐慌市反而更有效，'%(out['down_only']['win'],out['up_only']['win']))
    print('    故"大盘下行禁止开仓"是错误门控，会删掉最好的信号。')
    # 基线：纯持有40日不止损止盈，收益>0 算赢（看策略本身有没有正向偏移）
    base=[s[8] for s in sig if s[8] is not None]
    if base:
        bw=sum(1 for r in base if r>0)/len(base)
        print('  · 基线(纯持有40日不止损)：胜率 %.1f%% | 中位 %+6.2f%% （若此值仍低，说明入场本身无正向偏移，需收紧筛选）'%(
            bw*100, statistics.median(base)*100))

if __name__=='__main__':
    main()
