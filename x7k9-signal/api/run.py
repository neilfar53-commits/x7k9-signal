# api/run.py
# X7K9-ALPHA-BTC-2025 v4.1
import os
import json
import time
import requests
from datetime import datetime, timedelta

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Telegram 未配置，跳过通知")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Telegram 发送失败: {e}")

def get_okx_kline():
    url = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=15m&limit=50"
    res = requests.get(url, timeout=8)
    if res.status_code == 200:
        data = res.json()['data']
        closes = [float(d[4]) for d in data]
        highs = [float(d[2]) for d in data]
        lows = [float(d[3]) for d in data]
        # 计算 ATR(14)
        tr_list = []
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_list.append(tr)
        atr = sum(tr_list[-14:]) / 14
        return closes[-1], closes[-2], atr
    return None, None, None

def get_coinglass_data():
    base = "https://futures.coinglass.com"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # 1. 大户多空比 (OKX)
    try:
        res = requests.get(f"{base}/Position/longShortChart?symbol=BTC", headers=headers, timeout=8)
        long_short = float(res.json()['data'][-1]['longShortRate'])
    except:
        long_short = None

    # 2. 资金费率 (OKX)
    try:
        res = requests.get(f"{base}/openInterest/fundingRate?symbol=BTC&exchange=OKX", headers=headers, timeout=8)
        funding_rate = float(res.json()['data'][0]['rate'])
    except:
        funding_rate = None

    # 3. 交易所持仓 (OKX)
    try:
        res = requests.get(f"{base}/openInterest/positionsChange?symbol=BTC&exchange=OKX", headers=headers, timeout=8)
        holdings = float(res.json()['data'][-1]['holdings'])
        prev_holdings = float(res.json()['data'][-2]['holdings'])
        holding_change = (prev_holdings - holdings) / prev_holdings  # 正数 = 流出
    except:
        holding_change = None

    # 4. 爆仓数据
    try:
        res = requests.get(f"{base}/liquidation/chart?symbol=BTC", headers=headers, timeout=8)
        liq_data = res.json()['data'][-1]
        long_liq = liq_data['longLiquidation']
        short_liq = liq_data['shortLiquidation']
        liq_ratio = short_liq / (long_liq + short_liq) if (long_liq + short_liq) > 0 else 0.5
    except:
        liq_ratio = None

    # 5. 恐惧贪婪指数 + MVRV Z-Score
    try:
        res = requests.get(f"{base}/index/fearGreedIndex", headers=headers, timeout=8)
        fear_greed = int(res.json()['data'][-1]['value'])
        
        res = requests.get(f"{base}/index/mvrvZScore?symbol=BTC", headers=headers, timeout=8)
        mvrv_z = float(res.json()['data'][-1]['mvrvZScore'])
    except:
        fear_greed, mvrv_z = None, None

    return {
        'long_short': long_short,
        'funding_rate': funding_rate,
        'holding_change': holding_change,
        'liq_ratio': liq_ratio,
        'fear_greed': fear_greed,
        'mvrv_z': mvrv_z
    }

def check_news_alert():
    try:
        res = requests.get("https://api.coinglass.com/api/v1/news?category=market&limit=5", timeout=8)
        news = res.json()
        keywords = ["转入", "转出", "政策", "OKX", "Binance", "减税", "补贴"]
        for item in news:
            if any(kw in item['title'] for kw in keywords):
                return True, item['title']
    except:
        pass
    return False, ""

def main():
    print(f"[{datetime.now()}] 开始执行 X7K9-ALPHA-BTC-2025 v4.1")
    
    # 检查事件熔断
    event_triggered, event_title = check_news_alert()
    if event_triggered:
        msg = f"⚠️ 事件熔断触发！\n📰 {event_title}\n⏸️ 暂停交易1小时"
        send_telegram(msg)
        print("[!] 事件熔断，跳过本次评估")
        return

    # 获取价格 & ATR
    price, prev_price, atr = get_okx_kline()
    if not price or not atr:
        print("[!] K线获取失败")
        return

    # 获取 CoinGlass 数据
    cg = get_coinglass_data()

    # 六维条件判断
    cond1 = price > prev_price and atr < price * 0.02  # 波动不过大
    cond2 = cg['long_short'] is not None and 0.8 <= cg['long_short'] <= 1.3
    cond3 = cg['funding_rate'] is not None and -0.0003 <= cg['funding_rate'] <= 0.0005
    cond4 = cg['holding_change'] is not None and cg['holding_change'] >= 0.01  # 流出≥1%
    cond5 = cg['liq_ratio'] is not None and cg['liq_ratio'] > 0.55  # 空单爆仓主导
    cond6 = (
        cg['fear_greed'] is not None and 20 <= cg['fear_greed'] <= 80 and
        cg['mvrv_z'] is not None and -2 <= cg['mvrv_z'] <= 3
    )

    all_cond = cond1 and cond2 and cond3 and cond4 and cond5 and cond6

    # 构建报告
    status = "✅ 全部满足" if all_cond else "❌ 未触发"
    report = f"""
🚨 *X7K9-ALPHA-BTC-2025 v4.1* 评估报告

🕒 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} (UTC+8)
💰 当前价格: {price:,.0f} USDT
📊 六维状态:
  {'✅' if cond1 else '❌'} Cond1: 价格趋势 + ATR
  {'✅' if cond2 else '❌'} Cond2: 大户多空比={cg['long_short']:.2f}
  {'✅' if cond3 else '❌'} Cond3: 资金费率={cg['funding_rate']:.5f}
  {'✅' if cond4 else '❌'} Cond4: OKX持仓流出={cg['holding_change']:.1%}
  {'✅' if cond5 else '❌'} Cond5: 空单爆仓占比={cg['liq_ratio']:.1%}
  {'✅' if cond6 else '❌'} Cond6: 情绪中性 (恐贪={cg['fear_greed']}, MVRV-Z={cg['mvrv_z']:.1f})

🔔 结论: {status}
"""
    send_telegram(report)

    if all_cond:
        target = price * 1.022
        stop = price * 0.979
        action = f"\n🎯 *建议*: 手动在 OKX App 开多仓，挂止盈 {target:,.0f} (+2.2%)，止损 {stop:,.0f} (-2.1%)"
        send_telegram(action)

if __name__ == "__main__":
    main()
