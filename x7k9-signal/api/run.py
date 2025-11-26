# api/run.py
import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ===== 辅助函数 =====
def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))

def send_telegram(text):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("[!] Telegram 未配置，跳过通知")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        print("[✓] Telegram 通知已发送")
    except Exception as e:
        print(f"[!] Telegram 发送失败: {e}")

# ===== 数据采集 =====
def get_okx_btc_data():
    """获取 OKX BTC-USDT-SWAP 15m K线（可直连）"""
    try:
        url = "https://www.okx.com/api/v5/market/candles"
        params = {
            "instId": "BTC-USDT-SWAP",
            "bar": "15m",
            "limit": "5"
        }
        res = requests.get(url, params=params, timeout=10)
        if res.status_code != 200:
            return None
        data = res.json()
        if data['code'] != '0':
            return None
        # 最新K线
        latest = data['data'][0]
        open_p = float(latest[1])
        high = float(latest[2])
        low = float(latest[3])
        close = float(latest[4])
        atr = (high - low)  # 简化ATR
        return {
            "price": close,
            "atr_15m": round(atr, 1),
            "low_15m": low,
            "open_15m": open_p
        }
    except Exception as e:
        print(f"[!] OKX 数据获取失败: {e}")
        return None

def get_coinglass_long_short():
    """获取 CoinGlass 多空比（替代 BTC.D，可直连）"""
    try:
        # CoinGlass 公共API（无需Key）
        url = "https://futures.coinglass.com/Position/longShortChart"
        params = {"symbol": "BTC"}
        res = requests.get(url, params=params, timeout=10)
        if res.status_code != 200:
            return None
        data = res.json()
        if not data.get('data') or len(data['data']) == 0:
            return None
        # 取最新多空比
        ratio = float(data['data'][-1]['longShortRatio'])
        return ratio
    except Exception as e:
        print(f"[!] CoinGlass 数据获取失败: {e}")
        return None

def get_last_3_candles_color():
    """获取最近3根1分钟K线颜色（阳/阴）"""
    try:
        url = "https://www.okx.com/api/v5/market/candles"
        params = {"instId": "BTC-USDT-SWAP", "bar": "1m", "limit": "5"}
        res = requests.get(url, params=params, timeout=10)
        if res.status_code != 200:
            return []
        data = res.json()
        if data['code'] != '0':
            return []
        colors = []
        for c in data['data'][:3]:
            o = float(c[1])
            c_price = float(c[4])
            colors.append("green" if c_price > o else "red")
        return colors[::-1]  # 最近的在最后
    except Exception as e:
        print(f"[!] 1分钟K线获取失败: {e}")
        return []

def check_major_event():
    """简化：暂不接入宏观事件（可后续扩展）"""
    return False

# ===== X7K9 v4.1 信号判断 =====
def should_open_position(okx_data, long_short, candles, has_event):
    if not okx_data or long_short is None or len(candles) < 3:
        return False, {}

    price = okx_data["price"]
    atr = okx_data["atr_15m"]

    # 条件1: 多空比在合理区间（等效 BTC.D 50-65%）
    cond1 = 0.8 <= long_short <= 1.3

    # 条件2: 近3根1分钟K线为 2阳1阴 或 3阳
    valid_patterns = [
        ["green", "green", "red"],
        ["green", "green", "green"]
    ]
    cond2 = candles in valid_patterns

    # 条件3: 无重大事件
    cond3 = not has_event

    # 条件4: ATR > 200（高波动）
    cond4 = atr > 200

    if cond1 and cond2 and cond3 and cond4:
        tp = round(price * 1.023, 1)   # +2.3%
        sl = round(price * 0.988, 1)   # -1.2%
        return True, {
            "entry": price,
            "take_profit": tp,
            "stop_loss": sl,
            "atr": atr,
            "long_short": round(long_short, 2)
        }
    return False, {}

# ===== 主函数 =====
def main():
    now = beijing_now()
    print(f"\n[🕒] 开始运行 X7K9 信号检查 ({now.strftime('%Y-%m-%d %H:%M:%S')})")

    # 1. 获取数据
    okx = get_okx_btc_data()
    long_short = get_coinglass_long_short()
    candles = get_last_3_candles_color()
    event = check_major_event()

    print(f"[📊] OKX: {okx}")
    print(f"[📊] 多空比: {long_short}")
    print(f"[📊] K线颜色: {candles}")

    # 2. 判断信号
    signal, details = should_open_position(okx, long_short, candles, event)

    # 3. 输出结果
    result = {
        "timestamp": now.isoformat(),
        "okx_data": okx,
        "long_short_ratio": long_short,
        "last_3_candles": candles,
        "major_event": event,
        "x7k9_signal": {
            "triggered": signal,
            **details
        }
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # 4. 发送通知
    if signal:
        msg = (
            "🚨 *X7K9 交易信号触发！*\n\n"
            f"⏰ 时间: {now.strftime('%H:%M')}\n"
            f"💰 价格: {details['entry']} USDT\n"
            f"🎯 止盈: {details['take_profit']} (+2.3%)\n"
            f"🛑 止损: {details['stop_loss']} (-1.2%)\n"
            f"📊 ATR: {details['atr']}\n"
            f"📈 多空比: {details['long_short']}\n\n"
            "👉 请手动在 OKX App 开仓，并挂单！"
        )
        send_telegram(msg)
    else:
        print("[ℹ️] 无有效信号，继续等待。")

if __name__ == "__main__":
    main()