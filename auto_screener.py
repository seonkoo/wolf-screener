# -*- coding: utf-8 -*-
"""
小狼交易策略 · A股全自动扫描器
精确复刻 wolf-screener3.0.html 的 runScreening 四层判定逻辑：
  1️⃣ 情绪海选  -> 自建750日价格分位贪婪指数(calcGreedFromKline)
  2️⃣ 浪型过滤  -> 日线MACD金叉/绿柱缩短
  3️⃣ 技术共振  -> 15分钟MACD(金叉/底背离/绿柱缩短) + 日线布林(下轨/中轨)
  4️⃣ 资金校验  -> 近5日主力净流入(真实+K线估算)
Template: A建议低吸 / B观察 / C禁止 / D观望

数据：东方财富(push2delay 列表&资金流) + 腾讯(ifzq.gtimg.cn K线)
用法：python auto_screener.py  [topN=100]  [minInflow=0]
"""
import urllib.request, json, ssl, urllib.parse, math, random, sys, time, concurrent.futures, threading

CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
HDR = {'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'}

# ---- 回测验证后的最优参数(见 opt_backtest.py) ----
GREED_PASS = 40      # 低位/恐慌阈值：回测显示 <40 与 <35 胜率相近(64.7% vs 65.5%)但信号更多；原策略用35
HOLD_DAYS  = 40      # 最优持有期：均值回归需时间，10日过短(中位 +1.7% → 40日 +6.0%)
STOP_PCT   = 0.08    # 止损 8%
TP_PCT     = 0.15    # 止盈 15%

def get(u):
    req = urllib.request.Request(u, headers=HDR)
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8','ignore')

# ---------- 指标计算（与网页 JS 一一对应） ----------
def calc_ema(data, period):
    k = 2/(period+1); ema=[data[0]]
    for i in range(1,len(data)): ema.append(data[i]*k + ema[-1]*(1-k))
    return ema

def calc_macd(closes):
    if len(closes) < 30: return None
    e12=calc_ema(closes,12); e26=calc_ema(closes,26)
    dif=[e12[i]-e26[i] for i in range(len(closes))]
    dea=calc_ema(dif,9)
    macd=[(dif[i]-dea[i])*2 for i in range(len(closes))]
    return {'dif':dif,'dea':dea,'macd':macd}

def check_macd_cross(dif,dea):
    if len(dif)<2: return 'none'
    n=len(dif)
    if dif[n-2]<=dea[n-2] and dif[n-1]>dea[n-1]: return 'golden'
    if dif[n-2]>=dea[n-2] and dif[n-1]<dea[n-1]: return 'dead'
    if dif[n-1]>dea[n-1]: return 'above'
    return 'below'

def check_macd_green_shorten(macd):
    if len(macd)<3: return False
    n=len(macd)
    if macd[n-1]<0 and macd[n-2]<0 and macd[n-3]<0:
        return abs(macd[n-1])<abs(macd[n-2]) and abs(macd[n-2])<abs(macd[n-3])
    return False

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

# ---------- 数据获取 ----------
def get_secid(code):
    return ('1.' if code[0] in '69' else '0.')+code

def fetch_kline(code, period='day'):
    tcode=('sh' if code[0] in '69' else 'sz')+code
    varn='k'+code+'_'+str(random.randint(0,999999))
    if period=='min15':
        url='https://ifzq.gtimg.cn/appstock/app/kline/mkline?_var=%s&param=%s,min15,,,320'%(varn,tcode)
    else:
        url='https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=%s,day,,,320'%(varn,tcode)
    for _ in range(3):
        try:
            raw=get(url); raw=raw[raw.index('=')+1:]
            d=json.loads(raw); data=d.get('data',{}); kd=data.get(tcode,{})
            kl=kd.get('m15') if period=='min15' else (kd.get('day') or kd.get('qfqday'))
            if not kl: return []
            return [{'date':k[0],'open':float(k[1]),'close':float(k[2]),'high':float(k[3]),'low':float(k[4]),
                     'volume':float(k[5]) if len(k)>5 else 0} for k in kl]
        except Exception:
            time.sleep(0.15)
    return []

def fetch_fund_flow(secid):
    fields='&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65'
    url='https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get?secid=%s&lmt=5%s'%(secid,fields)
    for _ in range(2):
        try:
            d=json.loads(get(url))
            if d.get('data') and d['data'].get('klines'):
                return [{'date':k.split(',')[0],'main':float(k.split(',')[1])} for k in d['data']['klines']]
        except Exception:
            time.sleep(0.1)
    return []

# ---------- 四层判定（复刻 runScreening） ----------
def run_screening(stock):
    code=stock['code']; name=stock['name']; price=stock.get('price',0); chg=stock.get('change',0)
    res={'code':code,'name':name,'price':price,'change':chg,'inflow':stock.get('inflow',0),'template':'','suggestion':'',
         'stop':round(price*(1-STOP_PCT),3) if price else 0,'target':round(price*(1+TP_PCT),3) if price else 0,
         'l1':{},'l2':{},'l3':{},'l4':{},'flows':[]}
    kd=fetch_kline(code,'day')
    if not kd or len(kd)<30:
        res['l1']={'status':'wait','greed':0.0,'detail':'K线数据不足，无法计算贪婪指数'}
        res['template']='D'; res['suggestion']='K线数据不足，无法判定'; res['l2']={'status':'wait','detail':'K线数据不足'}
        res['l3']={'status':'wait','detail':'K线数据不足'}; res['l4']={'status':'wait','detail':'资金流数据不足'}
        return res
    day_closes=[k['close'] for k in kd]
    # Layer 1
    greed=calc_greed(day_closes)
    if greed<GREED_PASS: l1=('pass',greed,'低位/恐慌区间，入观察池')
    elif greed>65: l1=('fail',greed,'贪婪过热，禁止开仓')
    else: l1=('neutral',greed,'中性区间，观望')
    res['l1']={'status':l1[0],'greed':greed,'detail':'自建贪婪指数 %.1f%% → %s'%(greed,l1[1])}
    # Layer 2
    md=calc_macd(day_closes)
    if md:
        cr=check_macd_cross(md['dif'],md['dea'])
        if cr in ('golden','above'): res['l2']={'status':'pass','detail':'日线MACD金叉/DIF在DEA上方，存在反弹窗口'}
        else:
            gs=check_macd_green_shorten(md['macd'])
            if gs: res['l2']={'status':'wait','detail':'日线MACD零轴下方绿柱缩短，酝酿反弹'}
            else: res['l2']={'status':'fail','detail':'日线MACD死叉且绿柱未缩短，持续下行风险高'}
    else: res['l2']={'status':'wait','detail':'K线不足，无法判断浪型'}
    # Layer 3 — 优先用15分钟(与网页一致)；沙箱取不到15分钟时改用日线代理共振
    km=fetch_kline(code,'min15'); tech=0; l3macd='无明确信号'; div=False; gs15=False; l3_proxy=False
    if km and len(km)>30:
        m15=[k['close'] for k in km]; m15m=calc_macd(m15)
        if m15m:
            c15=check_macd_cross(m15m['dif'],m15m['dea']); div=check_macd_divergence(m15,m15m['dif'])
            gs15=check_macd_green_shorten(m15m['macd'])
            if div: tech+=1
            if c15=='golden': tech+=1; l3macd='15min金叉'
            elif gs15: tech+=1; l3macd='绿柱缩短'
            elif c15=='above': l3macd='DIF在DEA上方'
        l3boll=''
        if len(kd)>20:
            b=calc_bollinger(day_closes)
            if b:
                l3boll=b['position']
                if b['position'] in ('下轨支撑','中轨附近'): tech+=1
        l3status='pass' if tech>=2 else ('wait' if tech>=1 else 'fail')
        l3detail='15min MACD: '+l3macd+(' | 底背离✓' if div else '')+(' | 绿柱缩短✓' if gs15 else '')+' | 布林: '+l3boll
    else:
        # 日线代理共振（15分钟数据在扫描环境不可达，网页端用真实15min）
        l3_proxy=True
        closes=day_closes
        ma20=sum(closes[-20:])/20; price=closes[-1]
        lastvol=kd[-1]['volume']; avgvol=sum(k['volume'] for k in kd[-20:])/20 if len(kd)>=20 else 0
        b=calc_bollinger(closes); sig=[]
        if b and b['position'] in ('下轨支撑','中轨附近'): tech+=1; sig.append('布林'+b['position'])
        if price>=ma20: tech+=1; sig.append('站上MA20')
        if avgvol>0 and lastvol>1.5*avgvol: tech+=1; sig.append('放量×%.1f'%(lastvol/avgvol))
        if md and check_macd_divergence(closes,md['dif']): tech+=1; sig.append('日线底背离')
        l3status='pass' if tech>=2 else ('wait' if tech>=1 else 'fail')
        l3detail='日线代理共振(15min不可用): '+(' / '.join(sig) if sig else '无信号')
    res['l3']={'status':l3status,'detail':l3detail,'tech':tech,'proxy':l3_proxy}
    # Layer 4
    flows=fetch_fund_flow(get_secid(code))
    if flows and len(flows)<5:
        real={f['date'] for f in flows}
        for k in kd[-5:]:
            if k['date'] and k['date'] not in real and k['open']>0 and k['volume']>0:
                avg=(k['open']+k['close'])/2; turnover=k['volume']*100*avg; pct=(k['close']-k['open'])/k['open']
                flows.append({'date':k['date'],'main':turnover*pct,'estimated':True})
        flows.sort(key=lambda x:x['date'])
    res['flows']=flows
    l4status='wait'; l4flow=''; l4detail='资金流数据不足'
    if flows:
        recent=flows[-3:]; allout=all(f['main']<0 for f in recent)
        slowing=allout and abs(recent[-1]['main'])<abs(recent[0]['main'])
        last=recent[-1]; lastin=last['main']>0; amt=last['main']/1e8
        est=any(f.get('estimated') for f in flows)
        note=' (部分为价量估算)' if est else ''
        if lastin: l4status,l4flow,l4detail='pass','主力回流','最近一日主力净流入 %.2f亿%s'%((amt if amt>=0 else amt),note)
        elif slowing: l4status,l4flow,l4detail='wait','流出放缓','近3日持续流出但幅度收窄%s'%note
        elif allout: l4status,l4flow,l4detail='fail','持续流出','近3日主力持续净流出%s'%note
        else: l4status,l4flow,l4detail='neutral','资金mixed','资金流向不明朗%s'%note
    res['l4']={'status':l4status,'flow':l4flow,'detail':l4detail}
    # Layer 0 好公司过滤：仅当进入 A 候选(恐慌低位+技术共振)时才校验，避免全量拉取
    good_company=False; fund_detail=''
    if l1[0]=='pass' and l3status=='pass':
        if not YJ_MAP and not YJ_SNAPS:
            # 基本面数据完全不可用：保留技术信号，标注未验证(避免误杀)
            good_company=True; fund_detail='基本面数据暂不可用，技术信号保留(未验证好公司)'
        else:
            try:
                good_company, fund_detail = get_fundamentals(code)
            except Exception as e:
                good_company=True; fund_detail='基本面校验异常:%s，技术信号保留'%e
    res['fund']={'good':good_company,'detail':fund_detail}
    # Template
    if l1[0]=='fail': res['template']='C'; res['suggestion']='贪婪过热，禁止新开仓，持仓逢高逐步兑现。'
    elif res['l2']['status']=='fail': res['template']='D'; res['suggestion']='主跌阶段，观望，规避下跌风险。'
    elif l1[0]=='pass' and l3status=='pass':
        # 进入 A：低位 + 技术共振。好公司仅作"优先级"(回测显示好公司过滤不增Alpha，
        # 但会丢弃93%信号)，故不再硬降级为B，而是好公司排前、非好公司轻仓/观察。
        res['template']='A'
        if good_company:
            res['suggestion']='好公司+低位共振：小仓位分批低吸，持有约%d日做均值回归，止损%d%%目标%d%%，反弹属急跌修复，不长期持有。'%(
                HOLD_DAYS, int(STOP_PCT*100), int(TP_PCT*100))
        else:
            res['suggestion']='低位+技术共振(非好公司)：仅轻仓或观察，若参与同样止损%d%%目标%d%%；好公司优先级更低。'%(
                int(STOP_PCT*100), int(TP_PCT*100))
    else: res['template']='B'; res['suggestion']='纳入观察池，等待信号共振，暂不入场。'
    return res

# ---------- Layer 0: 好公司基本面过滤 ----------
# 规则：营收 同环比 正增长(YoY&QoQ) + ROE连续3年>8% + 经营现金流净额连续3年>0
YJ_MAP={}            # 最新一期业绩报表(实盘用)
YJ_MAP_PERIOD=None   # YJ_MAP 对应的报告期(用于判断是否年报)
YJ_SNAPS={}          # 历史各期业绩报表(回测 as-of 用)
FUND_LOCK=threading.Lock()

def load_yj_map(date=None):
    """载入业绩报表。date=None 载入最新一期到 YJ_MAP；给定 date 载入到 YJ_SNAPS[date]。"""
    global YJ_MAP, YJ_MAP_PERIOD
    import akshare as ak
    # 优先年报(12-31)：其"季度环比"=Q4 vs Q3 具参考意义；Q1单季环比因季节性普遍为负，不用于硬性过滤
    dates=[date] if date else ['20251231','20260331']
    for dt in dates:
        try:
            df=ak.stock_yjbb_em(date=dt)
            m={str(r['股票代码']):r for _,r in df.iterrows()}
            print('      业绩报表(%s) 载入 %d 只'%(dt,len(m)))
            if date: YJ_SNAPS[date]=m
            else: YJ_MAP=m; YJ_MAP_PERIOD=dt
            return m
        except Exception as e:
            print('      业绩报表(%s)失败: %s'%(dt,e))
    if date: YJ_SNAPS[date]={}
    return {}

def get_fundamentals(code, yj_row=None, asof=None, annual=None):
    """返回 (good, detail)。
       yj_row: 业绩报表行(含同环比增长)，不传则用 YJ_MAP[code]。
       asof:   'YYYY-MM-DD' 回测时点，过滤该时点前已披露的年报(避免未来函数)。
       annual: 该业绩报表是否为年报(12-31)。年报才纳入"季度环比(Q4 vs Q3)"硬性要求，
               避免 Q1 单季环比因季节性普遍为负而误杀。None 时按 YJ_MAP_PERIOD 推断。"""
    import akshare as ak
    import pandas as pd, datetime as _dt
    grow=False
    row=yj_row if yj_row is not None else YJ_MAP.get(code)
    if row is not None:
        try:
            rev_yoy=float(row['营业总收入-同比增长'])>0
            np_yoy=float(row['净利润-同比增长'])>0
            grow=rev_yoy and np_yoy
            if annual is None:
                annual = (YJ_MAP_PERIOD.endswith('1231') if YJ_MAP_PERIOD else False)
            if annual:
                rev_qoq=float(row['营业总收入-季度环比增长'])>0
                np_qoq=float(row['净利润-季度环比增长'])>0
                grow=grow and rev_qoq and np_qoq
        except Exception:
            grow=False
    roe_ok=ocf_ok=False
    try:
        if asof:
            ey=int(asof[:4]); sy=ey-3
        else:
            sy=_dt.datetime.now().year-3
        with FUND_LOCK:
            df=ak.stock_financial_analysis_indicator(symbol=code, start_year=str(sy))
        df=df.copy(); df['_d']=df['日期'].astype(str)
        if asof:
            df=df[pd.to_datetime(df['日期'])<=pd.Timestamp(asof[:10])]
        yr_df=df[df['_d'].str.endswith('12-31')].tail(3)
        if len(yr_df)>=3:
            roe_ok=all(float(x['净资产收益率(%)'])>8 for _,x in yr_df.iterrows())
            ocf_ok=all(float(x['每股经营性现金流(元)'])>0 for _,x in yr_df.iterrows())
    except Exception:
        pass
    good=bool(grow) and roe_ok and ocf_ok
    detail='ROE3年>8%%:%s 现金流3年>0:%s 增长(YoY%s):%s'%(roe_ok,ocf_ok,('&QoQ' if annual else ''),grow)
    return good, detail

# ---------- 全市场预筛 ----------
def get_universe(top_n, min_inflow):
    """候选预筛。
    ⚠️ 重要(回测结论)：不要再按"主力净流入"排序/过滤！回测证明高净流入名单会系统性漏掉
    真正的恐慌低位股(贪困<40 的票往往仍在被抛售、净流入为负)，导致信号质量骤降
    (按净流入预筛的回测仅 36% 胜率/-3.4% 中位；全市场宽扫描为 61-65% 胜率/+6% 中位)。
    改为：拉取较宽的全市场，按"当日跌幅"升序偏向已被打压的弱势股，再由四层逻辑精选。"""
    fs='m:0+t:6'
    out=[]
    for pn in range(1,16):   # 拉取更宽的全市场(约3000只)，供上层四层逻辑精选
        u='https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=200&fid=f3&po=0&fltt=2&invt=2&np=1&ut=fa5fd079d0a4d4f8f8f8f8&fs=%s&fields=f12,f14,f2,f3,f62'%(pn,urllib.parse.quote(fs))
        try:
            d=json.loads(get(u)); rows=d.get('data',{}).get('diff',[]) if d.get('data') else []
        except Exception:
            rows=[]
        if not rows: break
        out+=rows
        if len(out)>=3000: break
        time.sleep(0.08)
    cand=[]
    for r in out:
        code=str(r.get('f12') or ''); name=str(r.get('f14') or ''); inflow=0
        try: price=float(r.get('f2') or 0)
        except Exception: price=0
        try: chg=float(r.get('f3') or 0)
        except Exception: chg=0
        try: inflow=float(r.get('f62') or 0)
        except Exception: inflow=0
        if not code or len(code)<6: continue
        if code[0] in '849': continue          # 排除北交所/三板/B股
        if 'ST' in name or '退' in name: continue
        if price<2 or chg<-6 or chg>9.5: continue
        cand.append({'code':code,'name':name,'price':price,'change':chg,'inflow':inflow})
    # 按当日跌幅升序：越跌越靠前(更可能处于恐慌低位)，再由四层逻辑判定
    cand.sort(key=lambda x:x['change'])
    return cand[:top_n]

def main():
    top_n=int(sys.argv[1]) if len(sys.argv)>1 else 100
    min_inflow=float(sys.argv[2]) if len(sys.argv)>2 else 0
    print('[1/3] 拉取全市场按跌幅预筛 top%d (不再按净流入，避免漏掉恐慌低位股) ...'%(top_n))
    cand=get_universe(top_n, min_inflow)
    print('      预筛候选 %d 只，开始四层判定...'%(len(cand)))
    print('[2/3] 载入最新业绩报表(好公司过滤用)...')
    load_yj_map()
    if not YJ_MAP:
        print('      ⚠️ 业绩报表载入失败，好公司过滤将暂不启用(技术信号保留为A)')
    results=[]
    done=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futs={ex.submit(run_screening,c):c for c in cand}
        for f in concurrent.futures.as_completed(futs):
            done+=1
            r=f.result(); results.append(r)
            if done%10==0 or done==len(cand):
                print('      [%d/%d] %s %s -> %s'%(done,len(cand),r['code'],r['name'],r['template']))
    A=[r for r in results if r['template']=='A']
    B=[r for r in results if r['template']=='B']
    C=[r for r in results if r['template']=='C']
    D=[r for r in results if r['template']=='D']
    A.sort(key=lambda r:(0 if r.get('fund',{}).get('good',False) else 1, r['l1']['greed'], -r.get('inflow',0)))
    B.sort(key=lambda r:(r['l1']['greed'], -r.get('inflow',0)))
    # 输出
    goodA=[r for r in A if r.get('fund',{}).get('good',False)]
    print('\n========== 小狼策略 · A股自动扫描结果 ==========')
    print('候选 %d 只 | A建议买入 %d (其中好公司 %d) | B观察 %d | C禁止 %d | D观望 %d'%(len(results),len(A),len(goodA),len(B),len(C),len(D)))
    if any(r['l3'].get('proxy') for r in results):
        print('⚠️ 注：本扫描环境取不到15分钟K线，第3层"技术共振"改用日线代理(布林支撑/站上MA20/放量/日线底背离)。')
        print('   网页端(wolf-screener3.0.html)以真实15分钟MACD复核可得严格结论，两者第1/2/4层完全一致。')
    def line(r):
        g=r['l1']['greed']; inflow=r.get('inflow',0)/1e8
        tag='★好公司' if r.get('fund',{}).get('good',False) else ''
        return '%s %s %s 价%.2f 涨%.2f%%  贪婪%.1f%%  主力净流入%.2f亿  [%s/%s/%s/%s]'%(
            r['code'],r['name'],tag,r['price'],r['change'],g,inflow,
            r['l1']['status'],r['l2']['status'],r['l3']['status'],r['l4']['status'])
    print('\n--- 🟢 A 建议低吸（低位+技术共振，★好公司优先） ---')
    for r in A: print(' '+line(r)+'\n    '+r['suggestion'])
    print('\n--- 🟡 B 纳入观察池 ---')
    for r in B[:30]: print(' '+line(r))
    if C:
        print('\n--- 🔴 C 贪婪过热禁止 ---'); 
        for r in C[:10]: print(' '+line(r))
    if D:
        print('\n--- ⚪ D 主跌观望 ---')
        for r in D[:10]: print(' '+line(r))
    # 保存
    out={'generated':time.strftime('%Y-%m-%d %H:%M'),'summary':{'cand':len(results),'A':len(A),'B':len(B),'C':len(C),'D':len(D)},'A':A,'B':B,'C':C,'D':D}
    # 浏览器 JSON.parse 不接受 NaN/Infinity，写盘前先清洗成 null
    def _clean(o):
        if isinstance(o,dict): return {k:_clean(v) for k,v in o.items()}
        if isinstance(o,(list,tuple)): return [_clean(v) for v in o]
        if isinstance(o,float) and (math.isnan(o) or math.isinf(o)): return None
        return o
    json.dump(_clean(out), open('auto_screen_result.json','w',encoding='utf-8'), ensure_ascii=False, indent=1, allow_nan=False)
    print('\n✅ 已保存 auto_screen_result.json')

if __name__=='__main__':
    main()
