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

def clean_nan(o):
    """递归把 NaN/Infinity 换成 None，避免写出浏览器解析不了的 NaN（非法 JSON）。"""
    if isinstance(o, float):
        return o if (o == o and o != float('inf') and o != float('-inf')) else None
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_nan(v) for v in o]
    return o
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
lock=threading.Lock()

# ---- 对齐实跑参数 ----
GREED_PASS = 40
HOLD_DAYS  = 40
STOP_PCT   = 0.08
TP_PCT     = 0.15
COST_PCT   = 0.0025   # 单边往返交易成本（佣金+印花税+滑点，约0.25%），使回测收益=实盘可实现口径（仅扣成本，不改变策略优劣对比）

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
    返回 ('win'/'loss', 实际收益率(已扣交易成本 COST_PCT), 出场天数)。"""
    try: entry=float(kd[cp][2])
    except Exception: return None
    if entry<=0 or cp+hold>=len(kd): return None
    for i in range(1,hold+1):
        try: c=float(kd[cp+i][2])
        except Exception: break
        gross=c/entry-1
        if gross>=tp: return ('win', tp-COST_PCT, i)
        if gross<=-stop: return ('loss', -stop-COST_PCT, i)
    last=float(kd[cp+hold][2]); r=last/entry-1-COST_PCT
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
def momentum_score(kd, idx):
    """K线代理的"强势顺势"信号(L5≥2 的历史近似)：均线多头(ma5>ma10>ma20)+当日上涨+量价齐升(放量×1.5) 三选二。
    注：历史逐日主力净流入(f62)不可得，用"量价齐升+当日上涨"近似 L4 主力净流入>0；用于 S2/S3 回测。"""
    if idx<25: return 0
    closes=[float(k[2]) for k in kd[:idx+1]]
    if len(closes)<25: return 0
    ma5=sum(closes[-5:])/5; ma10=sum(closes[-10:])/10; ma20=sum(closes[-20:])/20
    if ma20<=0: return 0
    score=0
    if ma5>ma10>ma20: score+=1                      # 均线多头
    if closes[-1] > float(kd[idx-1][2]): score+=1    # 当日上涨(chg>0)
    try:
        vols=[float(k[5]) for k in kd[max(0,idx-19):idx+1]]; av=sum(vols)/len(vols); lastv=float(kd[idx][5])
        if av>0 and lastv>1.5*av: score+=1          # 量价齐升(放量)
    except Exception: pass
    return score

def features(kd, idx):
    """一次算出 greed / tech(L1+L3 日线代理) / momentum_score，供多策略复用，避免重复计算指标。"""
    cl=[float(k[2]) for k in kd[:idx+1]]
    greed=calc_greed(cl)
    tech=0
    if len(cl)>=30:
        b=calc_boll_pos(cl)
        if b and b in ('下轨支撑','中轨附近'): tech+=1
        ma20=sum(cl[-20:])/20
        if cl[-1]>=ma20: tech+=1
        vols=[float(k[5]) for k in kd[max(0,idx-19):idx+1]]; lastv=float(kd[idx][5]); av=sum(vols)/len(vols) if vols else 0
        if av>0 and lastv>1.5*av: tech+=1
        md=calc_macd(cl)
        if md and check_macd_divergence(cl,md['dif']): tech+=1
    return greed, tech, momentum_score(kd, idx)

def main():
    N=int(sys.argv[1]) if len(sys.argv)>1 else 600
    BARS=int(sys.argv[2]) if len(sys.argv)>2 else 600
    global TP_PCT, STOP_PCT
    TP_PCT=float(sys.argv[3]) if len(sys.argv)>3 else TP_PCT
    STOP_PCT=float(sys.argv[4]) if len(sys.argv)>4 else STOP_PCT
    HOLDS=[10,20,30,40]
    STRATS=['S0 纯持有基线','S1 小狼逆向(A)','S2 强势顺势(M)','S3 龙头顺势(M+龙头)']
    print('='*70)
    print('小狼策略 · 多策略 × 多持有期 walk-forward 回测')
    print('  参数: 贪婪<%d  止损%.0f%%  止盈%.0f%%  持有期=%s'%(GREED_PASS,STOP_PCT*100,TP_PCT*100,HOLDS))
    print('  S0纯持有基线 | S1小狼逆向(L1<40+L3) | S2强势顺势(均线多头+量价齐升) | S3龙头顺势(S2+行业龙头)')
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
    # 行业龙头集合（用于 S3 龙头顺势）
    leader_set=set()
    try:
        im=AS.load_industry_map(); ld=AS.build_leaders(im)
        leader_set={c for c,v in ld.items() if v.get('is_leader')}
        print('[3] 行业龙头股 %d 只（用于 S3 龙头顺势策略）'%len(leader_set))
    except Exception as e:
        print('  [warn] 龙头集构建失败，S3 退化为 S2:',e)
    # 检查点：每 12 个交易日重放一次（覆盖牛熊）
    sample=list(kdata.values())[0][1]; L=len(sample)
    cps=list(range(L-600, L-12, 12))
    cps=[c for c in cps if c>30]
    print('[4] 历史检查点:',len(cps),' 区间',sample[cps[0]][0],'~',sample[cps[-1]][0])
    # 聚合容器
    agg={s:{h:{'n':0,'w':0,'rets':[]} for h in HOLDS} for s in STRATS}
    for ci,cp in enumerate(cps):
        for code,(name,kd) in kdata.items():
            if cp>=len(kd)-max(HOLDS)-1: continue
            g,tech,mom=features(kd,cp)
            trig={'S0 纯持有基线':True,
                  'S1 小狼逆向(A)':(g<GREED_PASS and tech>=2),
                  'S2 强势顺势(M)':(mom>=2),
                  'S3 龙头顺势(M+龙头)':(mom>=2 and code in leader_set)}
            if not any(trig.values()): continue
            sims={h:simulate(kd,cp,hold=h) for h in HOLDS}   # 同一 (股票,时点) 只模拟一次，四策略共用
            for sname,on in trig.items():
                if not on: continue
                for h in HOLDS:
                    sim=sims.get(h)
                    if not sim: continue
                    win,ret,_=sim
                    a=agg[sname][h]; a['n']+=1; a['w']+=(1 if win=='win' else 0); a['rets'].append(ret)
        if (ci+1)%10==0:
            print('      检查点 %d/%d 完成'%(ci+1,len(cps)))
    print('[5] 回放完成')
    # 汇总矩阵
    matrix={}
    for sname in STRATS:
        matrix[sname]={}
        for h in HOLDS:
            a=agg[sname][h]; n=a['n']
            if n==0: matrix[sname][h]={'n':0,'win':0.0,'avg':None,'med':None}; continue
            rets=a['rets']; avg=sum(rets)/n; med=statistics.median(rets)
            matrix[sname][h]={'n':n,'win':round(a['w']/n*100,1),'avg':round(avg,4),'med':round(med,4)}
    # 结论：每个策略的最优持有期 + 相对基线超额（写进 JSON，前端直接展示，不让用户自己算）
    base=matrix['S0 纯持有基线']
    verdict=[]
    for sname in STRATS[1:]:
        row=matrix[sname]
        ok=[h for h in HOLDS if row[h]['n']]
        if not ok: continue
        best=max(ok, key=lambda h:(row[h]['avg'] or -9))
        ex=(row[best]['avg'] or 0)-(base[best]['avg'] or 0)
        verdict.append({'strategy':sname,'best_hold':best,'n':row[best]['n'],
                        'win':row[best]['win'],'avg':row[best]['avg'],
                        'excess':round(ex,4),'edge':bool(ex>0.005)})
    out={'generated':__import__('time').strftime('%Y-%m-%d %H:%M'),
         'params':{'greed_pass':GREED_PASS,'holds':HOLDS,'stop':STOP_PCT,'tp':TP_PCT,'cost':COST_PCT,
                   'pool':len(kdata),'checkpoints':len(cps),
                   'range':'%s ~ %s'%(sample[cps[0]][0],sample[cps[-1]][0])},
         'note':'S2/S3 的"主力净流入"用K线代理(均线多头+放量+当日上涨)近似，历史逐日 f62 资金流不可回溯，结论偏保守。',
         'strategies':STRATS,'matrix':matrix,'verdict':verdict}
    json.dump(clean_nan(out), open('backtest_winrate.json','w',encoding='utf-8'), ensure_ascii=False, indent=1, allow_nan=False)
    # 打印对比表
    print('\n=== 多策略 × 多持有期 回测对比（胜率% / 均值%） ===')
    print('%-22s'%'策略' + ''.join('%14s'%('%d日'%h) for h in HOLDS))
    for sname in STRATS:
        row='%-22s'%sname
        for h in HOLDS:
            c=matrix[sname][h]
            row += ('%13s'%('胜%.1f/均%.2f'%(c['win'],(c['avg'] or 0)*100))) if c['n'] else ('%13s'%'-')
        print(row)
    print('\n✅ 已保存 backtest_winrate.json（前端自动渲染对比表）')
    # 结论：S1/S2/S3 相对 S0 基线是否有超额
    print('\n结论速读（相对 S0 纯持有基线）：')
    for sname in STRATS[1:]:
        row=matrix[sname]
        base=matrix['S0 纯持有基线']
        line='  · %s: '%sname
        for h in HOLDS:
            cs=row[h]; cb=base[h]
            if cs['n'] and cb['n']:
                ex=(cs['avg'] or 0)-(cb['avg'] or 0)
                line+='  %d日[胜%.1f%% vs 基线%.1f%% · 收益%s%+.2f%%]'%(h, cs['win'], cb['win'], '超额' if ex>0 else '落后', ex*100)
        print(line)

if __name__=='__main__':
    main()
