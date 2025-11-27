# api/run.py
import os
import json
import requests
from datetime import datetime
from http.server import BaseHTTPRequestHandler       #Vercel 需要的 HTTP handler 基类

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Telegram 未配置")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[!] Telegram error: {e}")


def safe_get(data, *keys, default=None):
    """安全获取嵌套字典值"""
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        elif isinstance(data, list) and isinstance(key, int) and 0 <= key < len(data):
            data = data[key]
        else:
            return default
    return data


def get_okx_kline():
    try:
        url = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=15m&limit=50"
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            raw = res.json()
            data = safe_get(raw, 'data', default=[])
            if len(data) >= 2:
                closes = [float(d[4]) for d in data if len(d) > 4]
                highs = [float(d[2]) for d in data if len(d) > 2]
                lows = [float(d[3]) for d in data if len(d) > 3]
                if len(closes) >= 2 and len(highs) >= 2 and len(lows) >= 2:
                    tr_list = []
                    for i in range(1, min(15, len(highs))):
                        tr = max(
                            highs[i] - lows[i],
                            abs(highs[i] - closes[i-1]),
                            abs(lows[i] - closes[i-1])
                        )
                        tr_list.append(tr)
                    atr = sum(tr_list[-14:]) / len(tr_list[-14:]) if tr_list else 0
                    return closes[-1], closes[-2], atr
    except Exception as e:
        print(f"[!] OKX K线错误: {e}")
    return None, None, None


def get_coinglass_data():
    base = "https://futures.coinglass.com"
    headers = {"User-Agent": "Mozilla/5.0"}
    result = {
        'long_short': None,
        'funding_rate': None,
        'holding_change': None,
        'liq_ratio': None,
        'fear_greed': None,
        'mvrv_z': None
    }

    try:
        res = requests.get(f"{base}/Position/longShortChart?symbol=BTC", headers=headers, timeout=4)
        data = safe_get(res.json(), 'data')
        if data and len(data) >= 1:
            result['long_short'] = float(safe_get(data[-1], 'longShortRate', default=0))
    except:
        pass

    try:
        res = requests.get(f"{base}/openInterest/fundingRate?symbol=BTC&exchange=OKX", headers=headers, timeout=4)
        data = safe_get(res.json(), 'data')
        if data:
            result['funding_rate'] = float(safe_get(data[0], 'rate', default=0))
    except:
        pass

    try:
        res = requests.get(f"{base}/openInterest/positionsChange?symbol=BTC&exchange=OKX", headers=headers, timeout=4)
        data = safe_get(res.json(), 'data')
        if data and len(data) >= 2:
            prev = float(safe_get(data[-2], 'holdings', default=1))
            curr = float(safe_get(data[-1], 'holdings', default=1))
            if prev > 0:
                result['holding_change'] = (prev - curr) / prev
    except:
        pass

    try:
        res = requests.get(f"{base}/liquidation/chart?symbol=BTC", headers=headers, timeout=4)
        data = safe_get(res.json(), 'data')
        if data and len(data) >= 1:
            item = data[-1]
            long_liq = float(safe_get(item, 'longLiquidation', default=0))
            short_liq = float(safe_get(item, 'shortLiquidation', default=0))
            total = long_liq + short_liq
            result['liq_ratio'] = short_liq / total if total > 0 else 0.5
    except:
        pass

    try:
        res = requests.get(f"{base}/index/fearGreedIndex", headers=headers, timeout=4)
        data = safe_get(res.json(), 'data')
        if data and len(data) >= 1:
            result['fear_greed'] = int(safe_get(data[-1], 'value', default=50))
    except:
        pass

    try:
        res = requests.get(f"{base}/index/mvrvZScore?symbol=BTC", headers=headers, timeout=4)
        data = safe_get(res.json(), 'data')
        if data and len(data) >= 1:
            result['mvrv_z'] = float(safe_get(data[-1], 'mvrvZScore', default=0))
    except:
        pass

    return result


def check_news_alert():
    try:
        res = requests.get("https://api.coinglass.com/api/v1/news?category=market&limit=5", timeout=4)
        news = res.json()
        keywords = ["转入", "转出", "政策", "OKX", "Binance", "减税", "补贴"]
        for item in safe_get(news, 'data', default=[]):
            title = safe_get(item, 'title', default='')
            if any(kw in title for kw in keywords):
                return True, title
    except:
        pass
    return False, ""


def run_logic():
    """核心逻辑函数，避免与 Vercel 的 handler 冲突"""
    print(f"[{datetime.now()}] 开始执行 X7K9-ALPHA-BTC-2025 v4.1")

    event_triggered, event_title = check_news_alert()
    if event_triggered:
        msg = f"⚠️ 事件熔断触发！\n📰 {event_title}\n⏸️ 暂停交易1小时"
        send_telegram(msg)
        return

    price, prev_price, atr = get_okx_kline()
    # ⚠️ 保持你原来的判断逻辑，不改语义
    if not all([price, prev_price, atr is not None]):
        print("[!] K线数据不足")
        return

    cg = get_coinglass_data()

    cond1 = price > prev_price and atr < price * 0.02
    cond2 = cg['long_short'] is not None and 0.8 <= cg['long_short'] <= 1.3
    cond3 = cg['funding_rate'] is not None and -0.0003 <= cg['funding_rate'] <= 0.0005
    cond4 = cg['holding_change'] is not None and cg['holding_change'] >= 0.01
    cond5 = cg['liq_ratio'] is not None and cg['liq_ratio'] > 0.55
    cond6 = (
        cg['fear_greed'] is not None and 20 <= cg['fear_greed'] <= 80 and
        cg['mvrv_z'] is not None and -2 <= cg['mvrv_z'] <= 3
    )

    all_cond = cond1 and cond2 and cond3 and cond4 and cond5 and cond6

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


# ==============================
# ✅ Vercel 入口：改成类，不再用 (event, context)
# ==============================
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Vercel 会调用这个方法处理 /api/run 的 HTTP GET 请求"""
        try:
            run_logic()

            # 给调用方一个简单的 JSON 响应
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.wfile.write(body)
        except Exception as e:
            error_msg = f"[CRITICAL] Handler crashed: {str(e)}"
            print(error_msg)
            send_telegram(f"🚨 X7K9 系统错误:\n```\n{error_msg}\n```")

            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            body = json.dumps({"error": str(e)}).encode("utf-8")
            self.wfile.write(body)

    #  POST 也能触发，同样转到 GET 逻辑
    def do_POST(self):
        self.do_GET()


if __name__ == "__main__":
    run_logic()
