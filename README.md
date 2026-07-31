# 小狼自动选股（wolf-screener）

A股「恐慌低位 + 技术共振 + 好公司优先」自动选股雷达，云端定时运行并部署网页。

## 策略（小狼四层 + 好公司过滤）
- **L1 贪婪指数**：自建 750 日价格分位（恐慌低位 < 40 入池）
- **L2 日线 MACD**：非主跌阶段才考虑
- **L3 技术共振**：布林支撑 / 站上 MA20 / 放量 / 日线底背离，满足 ≥2 项
- **L4 资金校验**：主力净流入为正优先
- **好公司过滤（优先级，非硬门槛）**：年度+季度环比营收正增长、ROE 连续 3 年 >8%、经营现金流净额连续 3 年 >0；达标标 ★ 排前

> 回测结论：宽扫描 + 持有约 40 日 + 止损 8%/止盈 15% 显著优于旧「按净流入预筛 + 10 日持有」。详见 `opt_backtest.py` / `opt_result.json`。

## 文件
| 文件 | 作用 |
|---|---|
| `auto_screener.py` | 实盘扫描器（四层 + 好公司） |
| `opt_backtest.py` | 参数化回测沙盒（公平基准+防未来函数） |
| `backtest_screener.py` | 旧回测（保留对照） |
| `gen_auto_pick.py` | 由结果生成 `auto_pick.html` |
| `sync_auto_tab.py` | 把结果注入网页 Tab |
| `wolf-mobile4.2.html` / `wolf-screener3.0.html` | 手机/桌面版雷达 |
| `auto_pick.html` / `index.html` | 最新选股结果页 |

## 云端运行
GitHub Actions 工作日 **北京时间 08:30 / 10:30 / 14:00** 自动：扫描 → 回测验证 → 生成结果页 → 部署到 GitHub Pages。
仓库需开启 **Settings → Pages → Source: GitHub Actions**。

部署后手机访问：`https://seonkoo.github.io/wolf-screener/`
