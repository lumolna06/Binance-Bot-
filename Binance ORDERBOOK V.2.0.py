#FUNCIONAL
import json
import time
import threading
import websocket
from datetime import datetime, timedelta, timezone
from collections import deque
from binance.client import Client
from binance.enums import *
import math

# ===== CONFIGURACIÓN =====
API_KEY = "KNOHovcOWEDLeQkXh6xT27ZEwGnNN9r1kkBpefE36tgGpG7MyN7XjYv99byJG1xp"
API_SECRET = "81Q1smIhahcj7XjgJDfJwcp7v3mbb4MvQaLg42mF3R0TJO25GZxRO84j6g6MDOMZ"

SYMBOL = "ETHUSDC"
MONTO_USD = 25
APALANCAMIENTO = 10

VENTANA_HORAS = 1          # Ventana de horas para los trades recientes
RESET_CADA_HORAS = 1       # Reinicio cada X horas
DELTA_MINIMO = 1000
CONSISTENT_SIGNALS = 15
TAKE_PROFIT_PCT = 0.003    # 0.3%
EMA_INTERVAL = '1h'        # Intervalo de la EMA (1h)
MAX_TRADES = 8000          # 🔹 Número máximo fijo de trades a mantener (ajustable)

# ===== VARIABLES GLOBALES =====
pos_actual = None
primera_actualizacion = True
ultima_senal = None
contador_senal = 0
inicio_bot = datetime.now(timezone.utc)
deltas_recientes = []
historial_deltas = deque(maxlen=10)
ultima_ema_ts = None
cache_ema200 = None

# ===== CONEXIÓN BINANCE =====
client = Client(API_KEY, API_SECRET)

# ===== FUNCIONES AUXILIARES =====
def ajustar_cantidad(precio):
    qty = MONTO_USD / precio
    return round(qty, 3)

def cancelar_ordenes_pendientes():
    try:
        ordenes = client.futures_get_open_orders(symbol=SYMBOL)
        for o in ordenes:
            client.futures_cancel_order(symbol=SYMBOL, orderId=o["orderId"])
        if ordenes:
            print(f"🧹 {len(ordenes)} órdenes pendientes canceladas.")
    except Exception as e:
        print("❌ Error cancelando órdenes pendientes:", e)

def cerrar_todas():
    global pos_actual
    try:
        posiciones = client.futures_position_information(symbol=SYMBOL)
        for p in posiciones:
            qty = float(p["positionAmt"])
            if qty != 0:
                lado = SIDE_SELL if qty > 0 else SIDE_BUY
                print(f"🧹 Cerrando posición {lado} de {abs(qty)} ETH")
                client.futures_create_order(
                    symbol=SYMBOL,
                    side=lado,
                    type=ORDER_TYPE_MARKET,
                    quantity=abs(qty)
                )
        pos_actual = None
    except Exception as e:
        print("❌ Error cerrando posiciones:", e)

def abrir_posicion(tipo, ema200=None):
    global pos_actual
    try:
        cancelar_ordenes_pendientes()
        cerrar_todas()

        ticker = client.futures_symbol_ticker(symbol=SYMBOL)
        precio = float(ticker["price"])
        qty = ajustar_cantidad(precio)
        client.futures_change_leverage(symbol=SYMBOL, leverage=APALANCAMIENTO)

        # Filtro EMA
        if ema200 is not None:
            if tipo == "long" and precio <= ema200:
                print(f"✋ Filtro EMA: precio {precio:.4f} <= EMA200 {ema200:.4f} -> NO abrir LONG")
                return
            if tipo == "short" and precio >= ema200:
                print(f"✋ Filtro EMA: precio {precio:.4f} >= EMA200 {ema200:.4f} -> NO abrir SHORT")
                return

        lado = SIDE_BUY if tipo == "long" else SIDE_SELL
        print(f"🚀 Abriendo {tipo.upper()} por {qty} ETH @ {precio}")

        client.futures_create_order(
            symbol=SYMBOL,
            side=lado,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        # Take profit
        if tipo == "long":
            tp_price = round(precio * (1 + TAKE_PROFIT_PCT), 2)
            tp_side = SIDE_SELL
        else:
            tp_price = round(precio * (1 - TAKE_PROFIT_PCT), 2)
            tp_side = SIDE_BUY

        client.futures_create_order(
            symbol=SYMBOL,
            side=tp_side,
            type=ORDER_TYPE_LIMIT,
            timeInForce=TIME_IN_FORCE_GTC,
            quantity=qty,
            price=str(tp_price),
            reduceOnly=True
        )

        print(f"🎯 Take profit {tp_side} establecido en {tp_price}")
        pos_actual = tipo
    except Exception as e:
        print("❌ Error abriendo posición:", e)

# ===== EMA 200 =====
def calcular_ema200():
    global ultima_ema_ts, cache_ema200
    try:
        klines = client.futures_klines(symbol=SYMBOL, interval=EMA_INTERVAL, limit=1000)
        closes = [float(x[4]) for x in klines]
        alpha = 2 / (200 + 1)
        ema = closes[0]
        for price in closes[1:]:
            ema = (price - ema) * alpha + ema
        cache_ema200 = ema
        ultima_ema_ts = datetime.now(timezone.utc)
        return ema
    except Exception as e:
        print("❌ Error calculando EMA200:", e)
        return cache_ema200

# ===== HISTÓRICO =====
def cargar_trades_historicos():
    global deltas_recientes
    try:
        print(f"⏳ Descargando trades recientes para {SYMBOL}...")
        trades = []
        while len(trades) < MAX_TRADES:
            nuevos = client.futures_recent_trades(symbol=SYMBOL, limit=1000)
            trades.extend(nuevos)
            time.sleep(0.2)
            if len(trades) >= MAX_TRADES:
                break

        trades = trades[-MAX_TRADES:]  # 🔹 mantener solo los más recientes

        deltas_recientes.clear()
        for t in trades:
            qty = float(t["qty"])
            ts = datetime.fromtimestamp(t["time"] / 1000, tz=timezone.utc)
            is_sell = t["isBuyerMaker"]
            deltas_recientes.append({"time": ts, "qty": -qty if is_sell else qty})

        print(f"✅ {len(deltas_recientes)} trades cargados (fijos, máx {MAX_TRADES}).")
    except Exception as e:
        print("❌ Error al cargar trades históricos:", e)

# ===== REINICIO PROGRAMADO =====
def reset_bot_periodico():
    global deltas_recientes, historial_deltas, primera_actualizacion, ultima_senal, contador_senal
    global inicio_bot, cache_ema200, ultima_ema_ts, pos_actual
    while True:
        time.sleep(RESET_CADA_HORAS * 3600)
        try:
            print(f"\n♻️ ===== Reinicio del bot ({RESET_CADA_HORAS}h) =====")
            # Solo reinicia memoria local, no posiciones reales
            deltas_recientes = []
            historial_deltas = deque(maxlen=10)
            primera_actualizacion = True
            ultima_senal = None
            contador_senal = 0
            inicio_bot = datetime.now(timezone.utc)
            cache_ema200 = None
            ultima_ema_ts = None
            cargar_trades_historicos()
            print("♻️ Reinicio completo realizado.\n")
        except Exception as e:
            print("❌ Error durante reinicio:", e)

# ===== CALLBACKS WEBSOCKET =====
def on_message(ws, message):
    global deltas_recientes, cache_ema200, ultima_ema_ts, ultima_senal, contador_senal, pos_actual

    try:
        data = json.loads(message)
        ahora = datetime.now(timezone.utc)

        # --- Procesar trade ---
        qty = float(data["q"])
        is_sell = data["m"]
        deltas_recientes.append({"time": ahora, "qty": -qty if is_sell else qty})

        # --- Mantener tamaño fijo ---
        if len(deltas_recientes) > MAX_TRADES:
            deltas_recientes = deltas_recientes[-MAX_TRADES:]

        # --- Calcular delta actual ---
        compras = sum(d["qty"] for d in deltas_recientes if d["qty"] > 0)
        ventas = sum(-d["qty"] for d in deltas_recientes if d["qty"] < 0)
        delta_actual = compras - ventas  # positivo = más compras, negativo = más ventas

        # --- Actualizar EMA200 cada 60s ---
        if not ultima_ema_ts or (ahora - ultima_ema_ts).total_seconds() >= 60:
            ema200 = calcular_ema200()
        else:
            ema200 = cache_ema200

        precio = float(client.futures_symbol_ticker(symbol=SYMBOL)["price"])
        ema_texto = f"{ema200:.2f}" if ema200 else "N/A"
        print(f"🟢 {ahora.strftime('%H:%M:%S')} | Δ: {delta_actual:.2f} (Compras: {compras:.2f} | Ventas: {ventas:.2f}) | Precio: {precio:.2f} | EMA200: {ema_texto}")

        # --- Lógica de señal ---
        if pos_actual is None and ema200 is not None:
            if delta_actual >= DELTA_MINIMO and precio > ema200:
                if ultima_senal == "long":
                    contador_senal += 1
                else:
                    contador_senal = 1
                    ultima_senal = "long"
                if contador_senal >= CONSISTENT_SIGNALS:
                    abrir_posicion("long", ema200=ema200)
                    contador_senal = 0

            elif delta_actual <= -DELTA_MINIMO and precio < ema200:
                if ultima_senal == "short":
                    contador_senal += 1
                else:
                    contador_senal = 1
                    ultima_senal = "short"
                if contador_senal >= CONSISTENT_SIGNALS:
                    abrir_posicion("short", ema200=ema200)
                    contador_senal = 0

    except Exception as e:
        print("❌ Error en on_message:", e)

# ===== MAIN =====
def main():
    cargar_trades_historicos()
    calcular_ema200()
    threading.Thread(target=reset_bot_periodico, daemon=True).start()

    stream_url = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@trade"
    ws = websocket.WebSocketApp(stream_url, on_message=on_message)
    print("🚀 Bot iniciado y escuchando trades en tiempo real...")
    ws.run_forever()

if __name__ == "__main__":
    main()
