# -*- coding: utf-8 -*-
"""
小狼策略 · 历史回测验证器 (对齐实跑: A=贪婪<35 & 技术共振tech>=2)
新增 Layer 0 好公司过滤的 as-of 验证：用"信号发生时点"已披露的财报判断好公司，
杜绝未来函数。对比：
    [A全部(仅技术)]  vs  [A+好公司过滤]  vs  基准(同期沪深300样本均值)
用法：python backtest_screener.py  [poolN=1500]
"""
import urllib.request, json, ssl, urllib.parse, sys, threading, os, importlib.util, statistics
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
lock=threading.Lock()

# ---- 复用 auto_screener 的好公司判定 ----
_spec=importlib.util.spec_from_file_location('auto_screener', os.path.join(os.path.dirname(os.path.abspath(__file__)),'auto_screener.py'))
AS=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(AS)
load_yj_map=AS.load_yj_map; get_fundamentals=AS.get_fundamentals; YJ_SNAPS=AS.YJ_SNAPS

def get(u, ref='https://quote.eastmoney.com/'):
    req=urllib.request.Request(u, headers={'User-Agent':'Mozilla/5.0','Referer':ref})
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8','ignore')

def macd(closes, fast=12, slow=26, sig=9):
    ef=[closes[0]]; es=[closes[0]]
    for p in closes[1:]:
        ef.append(ef[-1]*2/(fast+1)+p*fast/(fast+1)); es.append(es[-1]*2/(slow+1)+p*slow/(slow+1))
    dif=[ef[i]-es[i] for i in range(len(closes))]
    dea=[dif[0]]
    for i in range(1,len(dif)): dea.append(dea[-1]*2/(sig+1)+dif[i]*sig/(sig+1))
    return dif,dea,[(dif[i]-dea[i])*2 for i in range(len(dif))]

def diverge(closes,dif):
    n=min(60,len(closes))
    if len(closes)<20 or len(dif)<20: return False
    pl=min(closes[-n:]); dl=min(dif[-n:])
    return closes[-1]<=pl*1.005 and dif[-1]>dl

def boll(closes,n=20):
    if len(closes)<n: return None
    w=closes[-n:]; ma=sum(w)/n; sd=(sum((x-ma)**2 for x in w)/n)**0.5
    lo,up=ma-2*sd,ma+2*sd; c=closes[-1]
    if c<=lo: return '下轨支撑'
    if c>=up: return '上轨压力'
    return '中轨附近' if c<ma else '中轨上方'

def est_inflow(k5):
    s=0
    for k in k5:
        o=float(k[1]); c=float(k[2]); v=float(k[5]); avg=(o+c)/2; s+=v*100*avg*(c-o)/o
    return s

def greed(closes):
    look=min(len(closes)-1,750); hist=closes[-look-1:-1]
    if not hist: return 50.0
    return sum(1 for x in hist if x<=closes[-1])/len(hist)*100

def screen(kd,idx):
    cl=[float(k[2]) for k in kd[:idx+1]]
    if len(cl)<30: return None
    gi=greed(cl); l1=gi<35
    tech=0
    b=boll(cl)
    if b and b in('下轨支撑','中轨附近'): tech+=1
    ma20=sum(cl[-20:])/20
    if cl[-1]>=ma20: tech+=1
    vols=[float(k[5]) for k in kd[max(0,idx-19):idx+1]]; lastv=float(kd[idx][5]); av=sum(vols)/len(vols)
    if av>0 and lastv>1.5*av: tech+=1
    m=macd(cl)
    if m and diverge(cl,m[0]): tech+=1
    l3=tech>=2
    return l1,l3,gi,tech

def report_date_for(d):
    """给定 'YYYY-MM-DD'，返回该时点已披露的最新单季业绩报表期次 'YYYYMMDD'。"""
    y=int(d[:4]); m=int(d[5:7])
    if 5<=m<=8: return '%d0331'%y
    if 9<=m<=10: return '%d0630'%y
    if m>=11: return '%d0930'%y
    return '%d1231'%(y-1)

def get_codes(N):
    try:
        import akshare as ak
        sh=ak.stock_info_sh_name_code(); sz=ak.stock_info_sz_name_code()
        def norm(df):
            cols=list(df.columns); cc='code' if 'code' in cols else ('symbol' if 'symbol' in cols else cols[0]); nc='name' if 'name' in cols else cols[1]
            return [(str(r[cc]), r[nc]) for _,r in df.iterrows()]
        codes=norm(sh)+norm(sz)
    except Exception as e:
        print('akshare列表失败,回退clist:',e); codes=[]
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

def main():
    N=int(sys.argv[1]) if len(sys.argv)>1 else 1500
    codes=get_codes(N)
    print('回测池:', len(codes))
    kdata={}
    def fetch(code,name):
        tc=('sh'+code) if code.startswith('6') else ('sz'+code)
        try:
            raw=get('https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,800'%tc,'https://gu.qq.com/'); raw=raw[raw.index('=')+1:]
            kd=json.loads(raw)['data'][tc]['day']
            if len(kd)>260:
                with lock: kdata[code]=(name,kd)
        except: pass
    ts=[threading.Thread(target=fetch,args=(c,nm)) for c,nm in codes]
    for t in ts: t.start()
    for t in ts: t.join()
    print('有效K线:',len(kdata))
    sample=list(kdata.values())[0][1]; L=len(sample)
    cps=list(range(L-250, L-10, 10))
    print('检查点:',len(cps), sample[cps[0]][0],'~',sample[cps[-1]][0])
    # 预载各期业绩报表(as-of)
    rep_dates=sorted({report_date_for(kdata[list(kdata.keys())[0]][1][cp][0]) for cp in cps})
    print('预载业绩报表期次:', rep_dates)
    for rd in rep_dates:
        load_yj_map(rd)
    sig=[]
    for cp in cps:
        cand=[]
        for code,(name,kd) in kdata.items():
            if cp<5: continue
            cand.append((est_inflow(kd[cp-4:cp+1]),code,name,kd))
        cand.sort(reverse=True); top=cand[:100]
        for inf,code,name,kd in top:
            r=screen(kd,cp)
            if not r: continue
            l1,l3,gi,tech=r
            if l1 and l3 and cp+10<len(kd):
                cp_date=kd[cp][0]
                rd=report_date_for(cp_date)
                row=YJ_SNAPS.get(rd,{}).get(code)
                good,fd=get_fundamentals(code, yj_row=row, asof=cp_date, annual=rd.endswith('1231'))
                ret=float(kd[cp+10][2])/float(kd[cp][2])-1
                sig.append((kd[cp][0],code,name,round(gi,1),tech,ret,good))
    print('\n=== 全A回测结果(对齐实跑: A=贪婪<35 & 技术共振tech>=2) ===')
    if not sig:
        print('一年内无A类信号'); return
    def stats(sub,label):
        if not sub:
            print('  %s: 无信号'%label); return
        rets=[s[5] for s in sub]; win=sum(1 for x in rets if x>0)/len(rets); avg=sum(rets)/len(rets)
        med=statistics.median(rets)
        print('  %-22s 信号%3d | 胜率 %5.1f%% | 平均10日 %+6.2f%% | 中位数 %+6.2f%%'%(
            label,len(sub),win*100,avg*100,med*100))
    stats(sig,'[A全部(仅技术)]')
    good_sig=[s for s in sig if s[6]]
    stats(good_sig,'[A+好公司过滤]')
    bench=[float(sample[cp+10][2])/float(sample[cp][2])-1 for cp in cps if cp+10<L]
    print('  %-22s 信号%3d | 胜率 %5.1f%% | 平均10日 %+6.2f%%'%( '基准(沪深300样本)',len(bench),
          sum(1 for x in bench if x>0)/len(bench)*100, sum(bench)/len(bench)*100))
    print('\n  [A+好公司过滤] 命中明细(收益降序):')
    for s in sorted(good_sig,key=lambda x:-x[5])[:20]:
        print('    %s %s %s  gi=%.1f tech=%d 10日 %+.1f%%'%(s[0],s[1],s[2],s[3],s[4],s[5]*100))
    n_good=len(good_sig); n_all=len(sig)
    print('\n  好公司占比: %d/%d = %.1f%%'%(n_good,n_all, n_all and n_good/n_all*100 or 0))

if __name__=='__main__': main()
