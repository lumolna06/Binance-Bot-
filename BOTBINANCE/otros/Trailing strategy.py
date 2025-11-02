import json
import time
import threading
import websocket
import logging
import sys
from datetime import datetime, timezone
from collections import deque
from binance.client import Client
from binance.enums import *
import numpy as np
import talib  # para SAR y ATR
from SAR_Bandera import verificar_desviacion  # importa al inicio del archivo


# ===== IMPORTAR CLASE EMA =====
from EMA import EMARealtime

# ===== CONFIGURACIÓN =====
API_KEY = "KNOHovcOWEDLeQkXh6xT27ZEwGnNN9r1kkBpefE36tgGpG7MyN7XjYv99byJG1xp"
API_SECRET = "81Q1smIhahcj7XjgJDfJwcp7v3mbb4MvQaLg42mF3R0TJO25GZxRO84j6g6MDOMZ"

SYMBOL = "ETHUSDC"
MONTO_USD = 1000
APALANCAMIENTO = 10

DELTA_MINIMO = 2000
CONSISTENT_SIGNALS = 60
TAKE_PROFIT_PCT = 0.003
EMA_INTERVAL = '30m'
MAX_TRADES = 8000
RESET_CADA_HORAS = 24

TRAILING_STOP_PCT = 0.003  # 0.3%
ATR_PERIOD = 14  # ATR para SL

# ===== LOGGING =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler("bot_ema_realtime.log", encoding='utf-8'),
              logging.StreamHandler(sys.stdout)]
)

# ===== VARIABLES =====
pos_actual = None
ultima_senal = None
contador_senal = 0
deltas_recientes = []
historial_deltas = deque(maxlen=10)
ultima_ema_ts = None

client = Client(API_KEY, API_SECRET)
ema_handler = EMARealtime(client, symbol=SYMBOL, interval=EMA_INTERVAL, length=200, data_limit=1500)

# ===== FUNCIONES =====
def verificar_posiciones_abiertas():
    """
    Verifica si hay posiciones abiertas en Binance y actualiza pos_actual.
    También registra el tamaño de la posición y su tipo (long/short).
    """
    global pos_actual
    try:
        posiciones = client.futures_position_information(symbol=SYMBOL)
        for p in posiciones:
            qty = float(p["positionAmt"])
            if qty != 0:
                if qty > 0:
                    pos_actual = "long"
                else:
                    pos_actual = "short"
                logging.info(f"⚠️ Posición abierta detectada al iniciar: {pos_actual.upper()} de {abs(qty)} ETH")
                return
        pos_actual = None
        logging.info("✅ No se detectaron posiciones abiertas al iniciar.")
    except Exception:
        logging.error("❌ Error al verificar posiciones abiertas:", exc_info=True)
        pos_actual = None


def ajustar_cantidad(precio):
    return round(MONTO_USD / precio, 3)

def cancelar_ordenes_pendientes():
    try:
        ordenes = client.futures_get_open_orders(symbol=SYMBOL)
        for o in ordenes:
            client.futures_cancel_order(symbol=SYMBOL, orderId=o["orderId"])
        if ordenes:
            logging.info(f"🧹 {len(ordenes)} órdenes pendientes canceladas.")
    except Exception as e:
        logging.error("❌ Error cancelando órdenes pendientes:", exc_info=True)

def cerrar_todas():
    global pos_actual
    try:
        posiciones = client.futures_position_information(symbol=SYMBOL)
        for p in posiciones:
            qty = float(p["positionAmt"])
            if qty != 0:
                lado = SIDE_SELL if qty > 0 else SIDE_BUY
                logging.info(f"🧹 Cerrando posición {lado} de {abs(qty)} ETH")
                client.futures_create_order(symbol=SYMBOL, side=lado, type=ORDER_TYPE_MARKET, quantity=abs(qty))
        pos_actual = None

        # ⚠️ Eliminar cualquier trailing stop residual
        cancelar_ordenes_pendientes()

    except Exception as e:
        logging.error("❌ Error cerrando posiciones:", exc_info=True)

def abrir_posicion(tipo):
    global pos_actual
    try:
        # ⚠️ Solo abrir si no hay posición actual
        if pos_actual is not None:
            logging.info(f"❌ No se puede abrir {tipo.upper()}, ya hay posición activa: {pos_actual.upper()}")
            return

        # Cancelar órdenes pendientes solo si no hay posición activa
        cancelar_ordenes_pendientes()
        cerrar_todas()

        ticker = client.futures_symbol_ticker(symbol=SYMBOL)
        precio = float(ticker["price"])
        qty = ajustar_cantidad(precio)
        client.futures_change_leverage(symbol=SYMBOL, leverage=APALANCAMIENTO)

        # ===== ATR para SL =====
        klines = client.futures_klines(symbol=SYMBOL, interval=EMA_INTERVAL, limit=ATR_PERIOD+1)
        highs = np.array([float(k[2]) for k in klines])
        lows = np.array([float(k[3]) for k in klines])
        closes = np.array([float(k[4]) for k in klines])
        atr = talib.ATR(highs, lows, closes, timeperiod=ATR_PERIOD)[-1]

        # Definir niveles de SL y TP
        if tipo == "long":
            sl_price = round(precio - 2 * atr, 2)
            tp_price = round(precio * (1 + TAKE_PROFIT_PCT), 2)
            lado = SIDE_BUY
            tp_side = SIDE_SELL
            sl_side = SIDE_SELL
        else:
            sl_price = round(precio + 2 * atr, 2)
            tp_price = round(precio * (1 - TAKE_PROFIT_PCT), 2)
            lado = SIDE_SELL
            tp_side = SIDE_BUY
            sl_side = SIDE_BUY

        logging.info(f"🚀 Abriendo {tipo.upper()} por {qty} ETH @ {precio}")
        client.futures_create_order(symbol=SYMBOL, side=lado, type=ORDER_TYPE_MARKET, quantity=qty)

        # ===== Take Profit =====
        client.futures_create_order(symbol=SYMBOL, side=tp_side, type=ORDER_TYPE_LIMIT,
                                    timeInForce=TIME_IN_FORCE_GTC, quantity=qty, price=str(tp_price), reduceOnly=True)
        logging.info(f"🎯 TP {tp_side} establecido en {tp_price}")

        # ===== Stop Loss =====
        client.futures_create_order(symbol=SYMBOL, side=sl_side, type="STOP_MARKET",
                                    stopPrice=str(sl_price), closePosition=True)
        logging.info(f"🛑 SL {sl_side} establecido en {sl_price} (ATR x2)")

        # ===== Trailing Stop =====
        """
        if tipo == "long":
            activation_price = round(precio * (1 + 0.003), 2)
        else:
            activation_price = round(precio * (1 - 0.003), 2)

        client.futures_create_order(
            symbol=SYMBOL,
            side=sl_side,
            type="TRAILING_STOP_MARKET",
            activationPrice=str(activation_price),
            callbackRate=TRAILING_STOP_PCT * 100,
            quantity=qty
        )
        logging.info(f"🔁 Trailing Stop {sl_side} se activará tras +0.3% de ganancia (activación: {activation_price}, trailing: {TRAILING_STOP_PCT*100:.1f}%)")
        """
        pos_actual = tipo

    except Exception as e:
        logging.error("❌ Error abriendo posición:", exc_info=True)

# ===== RESTO DEL CÓDIGO =====
def cargar_trades_historicos():
    global deltas_recientes
    try:
        logging.info(f"⏳ Descargando trades recientes para {SYMBOL}...")
        trades = []
        while len(trades) < MAX_TRADES:
            nuevos = client.futures_recent_trades(symbol=SYMBOL, limit=1000)
            trades.extend(nuevos)
            time.sleep(0.2)
            if len(nuevos) < 1000 or len(trades) >= MAX_TRADES:
                break

        trades = trades[-MAX_TRADES:]
        deltas_recientes.clear()
        for t in trades:
            qty = float(t["qty"])
            ts = datetime.fromtimestamp(t["time"] / 1000, tz=timezone.utc)
            is_sell = t["isBuyerMaker"]
            deltas_recientes.append({"time": ts, "qty": -qty if is_sell else qty})

        logging.info(f"✅ {len(deltas_recientes)} trades cargados (máx {MAX_TRADES}).")
    except Exception as e:
        logging.error("❌ Error al cargar trades históricos:", exc_info=True)

def reset_bot_periodico():
    global deltas_recientes, historial_deltas, ultima_senal, contador_senal, pos_actual
    while True:
        time.sleep(RESET_CADA_HORAS * 3600)
        try:
            logging.info(f"\n♻️ ===== Reinicio del bot ({RESET_CADA_HORAS}h) =====")
            deltas_recientes = []
            historial_deltas = deque(maxlen=10)
            ultima_senal = None
            contador_senal = 0
            pos_actual = None
            cargar_trades_historicos()
            ema_handler.inicializar_ema()
            logging.info("♻️ Reinicio completo realizado.\n")
        except Exception:
            logging.error("❌ Error durante reinicio:", exc_info=True)

def on_message(ws, message):
    global deltas_recientes, ultima_senal, contador_senal, pos_actual, ultima_ema_ts
    try:
        data = json.loads(message)
        ahora = datetime.now(timezone.utc)

        # precio y campos desde WS
        ws_price = float(data.get("p", 0))
        qty = float(data.get("q", 0))
        is_sell = data.get("m", False)

        # Obtener precio REST y usarlo para la lógica y logs.
        # Si falla por cualquier motivo, usamos fallback al precio del WS.
        try:
            rest_ticker = client.futures_symbol_ticker(symbol=SYMBOL)
            rest_price = float(rest_ticker.get("price", 0))
            if rest_price == 0:
                # seguridad: si REST devolvió 0 tratarlo como fallo
                rest_price = None
        except Exception:
            rest_price = None

        # Precio final que se usará para señales y logs (REST preferred)
        precio = rest_price if (rest_price is not None) else ws_price

        # Log comparativo (útil para diagnosticar diferencias); no cambia la lógica
        #logging.info(f"🔎 Precio REST={'{:.2f}'.format(rest_price) if rest_price is not None else 'N/A'} | Precio WS={ws_price:.2f} | hora={ahora.strftime('%H:%M:%S')}")

        deltas_recientes.append({"time": ahora, "qty": -qty if is_sell else qty})
        if len(deltas_recientes) > MAX_TRADES:
            deltas_recientes = deltas_recientes[-MAX_TRADES:]

        compras = sum(d["qty"] for d in deltas_recientes if d["qty"] > 0)
        ventas = sum(-d["qty"] for d in deltas_recientes if d["qty"] < 0)
        delta_actual = compras - ventas

        now_ts = datetime.now(timezone.utc)
        if not ultima_ema_ts or (now_ts - ultima_ema_ts).total_seconds() >= 1800:
            ema_handler.inicializar_ema()
            ultima_ema_ts = now_ts

        ema200 = float(ema_handler.get_ema())
        klines = client.futures_klines(symbol=SYMBOL, interval=EMA_INTERVAL, limit=150)
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        sar = talib.SAR(np.array(highs), np.array(lows), acceleration=0.02, maximum=0.2)
        sar_actual = sar[-1]

        logging.info(f"📊 Δ={delta_actual:.2f} | Precio={precio:.2f} | EMA200={ema200:.2f} | SAR={sar_actual:.2f}")

        if pos_actual is None and ema200 is not None:
            # VALIDAR que el precio sea mayor que cero
            if precio > 0:
                # LONG
                if precio > ema200 and precio > sar_actual and delta_actual >= DELTA_MINIMO:
                    if ultima_senal == "long":
                        contador_senal += 1
                    else:
                        contador_senal = 1
                        ultima_senal = "long"
                    if contador_senal >= CONSISTENT_SIGNALS:
                        # ✅ Verificar bandera SAR una sola vez antes de abrir
                        if not verificar_desviacion():  # solo abrir si desviación < 1%
                            abrir_posicion("long")
                        else:
                            logging.info("⚠️ Señal LONG descartada por bandera SAR (desviación > 1%)")
                        contador_senal = 0
                # SHORT
                elif precio < ema200 and precio < sar_actual and delta_actual <= -DELTA_MINIMO:
                    if ultima_senal == "short":
                        contador_senal += 1
                    else:
                        contador_senal = 1
                        ultima_senal = "short"
                    if contador_senal >= CONSISTENT_SIGNALS:
                        # ✅ Verificar bandera SAR una sola vez antes de abrir
                        if not verificar_desviacion():  # solo abrir si desviación < 1%
                            abrir_posicion("short")
                        else:
                            logging.info("⚠️ Señal SHORT descartada por bandera SAR (desviación > 1%)")
                        contador_senal = 0
            else:
                logging.warning(f"⚠️ Precio inválido recibido: {precio}. Señal ignorada.")

    except Exception:
        logging.error("❌ Error en on_message:", exc_info=True)

def main():
    cargar_trades_historicos()
    ema_handler.inicializar_ema()
    verificar_posiciones_abiertas()
    threading.Thread(target=reset_bot_periodico, daemon=True).start()
    stream_url = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@trade"
    ws = websocket.WebSocketApp(stream_url, on_message=on_message)
    logging.info("🚀 Bot iniciado y escuchando trades en tiempo real...")
    ws.run_forever()

if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception:
            logging.error("💥 Error crítico en el bot:", exc_info=True)
            logging.info("🔁 Reiniciando en 10 segundos...")
            time.sleep(10)
