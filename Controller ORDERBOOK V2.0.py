import pandas as pd
import numpy as np
from binance.client import Client
from datetime import datetime, timezone
import time

# ===== CONFIGURACIÓN =====
API_KEY = "KNOHovcOWEDLeQkXh6xT27ZEwGnNN9r1kkBpefE36tgGpG7MyN7XjYv99byJG1xp"
API_SECRET = "81Q1smIhahcj7XjgJDfJwcp7v3mbb4MvQaLg42mF3R0TJO25GZxRO84j6g6MDOMZ"
SYMBOL = "ETHUSDC"
INTERVAL = "30m"
EMA_PERIOD = 200
HISTORICAL_MULTIPLIER = 5
SAR_STEP = 0.02
SAR_MAX = 0.2

client = Client(API_KEY, API_SECRET)

# ===== FUNCIONES =====
def get_historical_klines(symbol, interval, limit):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
        'quote_asset_volume', 'number_of_trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

def add_ema(df, period=EMA_PERIOD):
    df['EMA200'] = df['close'].ewm(span=period, adjust=False).mean()
    return df

def detect_structure(df):
    df['HH'] = False
    df['HL'] = False
    df['LH'] = False
    df['LL'] = False
    df['trend'] = pd.Series([None] * len(df), dtype=object)

    for i in range(2, len(df) - 1):
        prev1, prev2 = df['high'].iloc[i - 1], df['high'].iloc[i - 2]
        high, low = df['high'].iloc[i], df['low'].iloc[i]

        if high > prev1 and prev1 > prev2:
            df.at[i, 'HH'] = True
        elif high < prev1 and prev1 < prev2:
            df.at[i, 'LH'] = True

        if low > prev1 and prev1 > prev2:
            df.at[i, 'HL'] = True
        elif low < prev1 and prev1 < prev2:
            df.at[i, 'LL'] = True

        if df.at[i, 'HH'] or df.at[i, 'HL']:
            df.at[i, 'trend'] = 'up'
        elif df.at[i, 'LH'] or df.at[i, 'LL']:
            df.at[i, 'trend'] = 'down'
    return df

def calculate_sar(df, step=SAR_STEP, max_af=SAR_MAX):
    sar = [df['low'][0]]
    trend = 1 if df['close'][1] > df['close'][0] else -1
    ep = df['high'][0] if trend == 1 else df['low'][0]
    af = step

    for i in range(1, len(df)):
        prev_sar = sar[-1]
        if trend == 1:
            curr_sar = prev_sar + af * (ep - prev_sar)
            curr_sar = min(curr_sar, df['low'].iloc[i - 1], df['low'].iloc[i - 2] if i > 1 else df['low'].iloc[i - 1])
            if df['low'].iloc[i] < curr_sar:
                trend = -1
                curr_sar = ep
                ep = df['low'].iloc[i]
                af = step
            else:
                if df['high'].iloc[i] > ep:
                    ep = df['high'].iloc[i]
                    af = min(af + step, max_af)
        else:
            curr_sar = prev_sar + af * (ep - prev_sar)
            curr_sar = max(curr_sar, df['high'].iloc[i - 1],
                           df['high'].iloc[i - 2] if i > 1 else df['high'].iloc[i - 1])
            if df['high'].iloc[i] > curr_sar:
                trend = 1
                curr_sar = ep
                ep = df['high'].iloc[i]
                af = step
            else:
                if df['low'].iloc[i] < ep:
                    ep = df['low'].iloc[i]
                    af = min(af + step, max_af)
        sar.append(curr_sar)

    df['SAR'] = sar
    df['SAR_trend'] = np.where(df['close'] > df['SAR'], 'up', 'down')
    return df

def detect_advanced_patterns(df):
    df['bullish_engulfing'] = (df['close'] > df['open']) & (df['open'].shift(1) > df['close'].shift(1)) & (df['close'] > df['open'].shift(1))
    df['bearish_engulfing'] = (df['close'] < df['open']) & (df['open'].shift(1) < df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
    df['hammer'] = ((df['close'] - df['low']) > 2 * (df['open'] - df['close'])) & ((df['close'] - df['open']) > 0)
    df['shooting_star'] = ((df['high'] - df['close']) > 2 * (df['close'] - df['open'])) & ((df['close'] - df['open']) > 0)
    df['morning_star'] = ((df['close'].shift(2) < df['open'].shift(2)) & (df['close'].shift(1) < df['open'].shift(1)) & (df['close'] > df['open'].shift(1)) & (df['close'] > df['close'].shift(2)))
    df['evening_star'] = ((df['close'].shift(2) > df['open'].shift(2)) & (df['close'].shift(1) > df['open'].shift(1)) & (df['close'] < df['open'].shift(1)) & (df['close'] < df['close'].shift(2)))
    df['piercing_line'] = ((df['close'].shift(1) < df['open'].shift(1)) & (df['close'] > df['open'].shift(1)) & (df['close'] < df['open'].shift(1) + (df['open'].shift(1) - df['close'].shift(1)) / 2))
    df['dark_cloud_cover'] = ((df['close'].shift(1) > df['open'].shift(1)) & (df['close'] < df['open'].shift(1)) & (df['close'] > df['open'].shift(1) - (df['close'].shift(1) - df['open'].shift(1)) / 2))
    df['tweezer_top'] = (df['high'].shift(1).round(2) == df['high'].round(2)) & (df['close'].shift(1) < df['open'].shift(1))
    df['tweezer_bottom'] = (df['low'].shift(1).round(2) == df['low'].round(2)) & (df['close'].shift(1) > df['open'].shift(1))
    return df

def generate_signals(df):
    for i in range(1, len(df)):
        price = df['close'].iloc[i]
        ema = df['EMA200'].iloc[i]
        trend = df['trend'].iloc[i]
        sar_trend = df['SAR_trend'].iloc[i]
        timestamp = df['timestamp'].iloc[i]

        print(f"[DEBUG] Procesando vela: {timestamp} - Precio: {price:.2f}, EMA200: {ema:.2f}, SAR_trend: {sar_trend}, Trend: {trend}")

        direction = None
        if price > ema and sar_trend == 'up':
            direction = 'long'
        elif price < ema and sar_trend == 'down':
            direction = 'short'

        if direction is None or trend is None:
            continue

        bullish_patterns = ['bullish_engulfing', 'hammer', 'morning_star', 'piercing_line', 'tweezer_bottom']
        bearish_patterns = ['bearish_engulfing', 'shooting_star', 'evening_star', 'dark_cloud_cover', 'tweezer_top']

        bullish = any(df[p].iloc[i] for p in bullish_patterns)
        bearish = any(df[p].iloc[i] for p in bearish_patterns)

        if direction == 'long' and bullish and trend == 'up':
            print(f"[SEÑAL COMPRA] {timestamp} - Precio: {price:.2f}")
        elif direction == 'short' and bearish and trend == 'down':
            print(f"[SEÑAL VENTA] {timestamp} - Precio: {price:.2f}")

def es_media_hora_cerrada():
    """Devuelve True solo cuando es un múltiplo de 30 minutos naturales."""
    ahora = datetime.now(timezone.utc)
    return (ahora.minute % 30 == 0) and (ahora.second < 10)

# ===== LOOP PRINCIPAL =====
if __name__ == "__main__":
    INITIAL_LIMIT = EMA_PERIOD * HISTORICAL_MULTIPLIER

    df = get_historical_klines(SYMBOL, INTERVAL, INITIAL_LIMIT)
    df = add_ema(df)
    df = detect_structure(df)
    df = detect_advanced_patterns(df)
    df = calculate_sar(df)
    df_closed = df.iloc[:-1].copy()

    print(f"[DEBUG] Iniciando backtest con {len(df_closed)} velas cerradas")
    generate_signals(df_closed)
    last_timestamp = df_closed['timestamp'].iloc[-1]
    print(f"[DEBUG] Última vela procesada: {last_timestamp}")

    while True:
        if es_media_hora_cerrada():
            print("[DEBUG] Cierre de vela detectado, procesando...")
            df = get_historical_klines(SYMBOL, INTERVAL, INITIAL_LIMIT)
            df = add_ema(df)
            df = detect_structure(df)
            df = detect_advanced_patterns(df)
            df = calculate_sar(df)
            df_closed = df.iloc[:-1].copy()

            new_df = df_closed[df_closed['timestamp'] > last_timestamp]
            if not new_df.empty:
                generate_signals(new_df)
                last_timestamp = new_df['timestamp'].iloc[-1]
                print(f"[DEBUG] Nueva vela procesada: {last_timestamp}")
        else:
            ahora = datetime.now(timezone.utc)
            print(f"[DEBUG] Esperando cierre... hora actual: {ahora.strftime('%H:%M:%S')}")

        time.sleep(10)
