import json
import time
import threading
import websocket
import logging
import sys
from datetime import datetime, timezone, timedelta
import numpy as np
import talib  # para SAR y ATR
from binance.client import Client
from binance.enums import *
from SAR_Bandera import verificar_desviacion  # importa al inicio del archivo
from EMA import EMARealtime
#from TrendWS import actualizar_trend, trend_actual
import TrendWS
from PositionChecker import PositionChecker
from SAR_Bandera import obtener_sar_inicial_real, obtener_sar_completo, calcular_desviacion
from TrendLimiter import TrendLimiter
from logger_config import LoggerConfig

"verificdor de tendencia"
import asyncio
import websockets
import json
from collections import deque
from datetime import datetime

# 🔹 Configurar logger antes de todo lo demás
LoggerConfig.configurar_logger(
    carpeta="logs",
    dias_guardados=7,
    telegram_token="8374373396:AAGrVx2Da2WEhuURiWGQklmyeIy6Je3X3Jg",
    telegram_chat_id="7826670887"
)

# 🔹 Ya puedes usar logging en todo el bot
logging.info("✅ Bot iniciado correctamente")
logging.warning("⚠️ Advertencia de ejemplo")
logging.error("❌ Error de ejemplo: prueba de envío a Telegram")

# ===== CONFIGURACIÓN =====
# bien
API_KEY = "KNOHovcOWEDLeQkXh6xT27ZEwGnNN9r1kkBpefE36tgGpG7MyN7XjYv99byJG1xp"
API_SECRET = "81Q1smIhahcj7XjgJDfJwcp7v3mbb4MvQaLg42mF3R0TJO25GZxRO84j6g6MDOMZ"

SYMBOL = "ETHUSDC"
MONTO_USD = 25
APALANCAMIENTO = 30

DELTA_MINIMO = 2000
CONSISTENT_SIGNALS = 30
TAKE_PROFIT_PCT = 0.003
EMA_INTERVAL = '30m'
#RESET_CADA_MINUTOS = 720  # reinicio cada 10 minutos exactos

TRAILING_STOP_PCT = 0.003  # 0.3%
ATR_PERIOD = 14  # ATR para SL
UMBRAL_PCT_FIJO = 5.0  # porcentaje fijo
VELAS_ATRAS = 1  # además de la actual, cuántas velas atrás considerar

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
ultima_ema_ts = None
deltas_buffer = {}  # clave = start_ts de la vela, valor = lista de deltas
velas_cargadas = False  # <--- AQUÍ
#trend_actual = "flat"


client = Client(API_KEY, API_SECRET)
ema_handler = EMARealtime(client, symbol=SYMBOL, interval=EMA_INTERVAL, length=200, data_limit=1500)
pos_checker = PositionChecker(client, SYMBOL, intervalo=30)
pos_checker.start_monitor()

# ===== LIMITADOR DE OPERACIONES POR TENDENCIA =====
limitador = TrendLimiter(max_ops_por_tendencia=1)   # <--- inicialización aquí ultimo cambio

# ===== FUNCIONES =====
def verificar_posiciones_abiertas():
    global pos_actual
    try:
        posiciones = client.futures_position_information(symbol=SYMBOL)
        for p in posiciones:
            qty = float(p["positionAmt"])
            if qty != 0:
                pos_actual = "long" if qty > 0 else "short"
                logging.info(f"⚠️ Posición abierta detectada al iniciar: {pos_actual.upper()} de {abs(qty)} ETH")
                return
        pos_actual = None
        logging.info("✅ No se detectaron posiciones abiertas al iniciar.")
    except Exception:
        logging.error("❌ Error al verificar posiciones abiertas:", exc_info=True)
        pos_actual = None


def ajustar_cantidad(precio):
    return round(MONTO_USD / precio, 3)

def limpiar_deltas_viejos():
    """
    Mantiene en el buffer solo la vela actual y las VELAS_ATRAS anteriores.
    Borra las demás velas antiguas y loguea qué velas se eliminaron.
    """
    global deltas_buffer
    if not deltas_buffer:
        return

    max_velas = VELAS_ATRAS + 1  # actual + atras
    claves_ordenadas = sorted(deltas_buffer.keys())

    while len(deltas_buffer) > max_velas:
        key_antigua = claves_ordenadas.pop(0)
        del deltas_buffer[key_antigua]
        logging.info(f"🧹 Vela {datetime.fromtimestamp(key_antigua/1000)} eliminada. Quedan {len(deltas_buffer)} velas en buffer.")

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
        cancelar_ordenes_pendientes()
    except Exception as e:
        logging.error("❌ Error cerrando posiciones:", exc_info=True)


def abrir_posicion(tipo):
    global pos_actual
    try:
        verificar_posiciones_abiertas()

        if pos_actual is not None:
            logging.info(f"❌ No se puede abrir {tipo.upper()}, ya hay posición activa: {pos_actual.upper()}")
            return False
        cancelar_ordenes_pendientes()
        cerrar_todas()

        ticker = client.futures_symbol_ticker(symbol=SYMBOL)
        precio = float(ticker["price"])
        qty = ajustar_cantidad(precio)
        client.futures_change_leverage(symbol=SYMBOL, leverage=APALANCAMIENTO)

        klines = client.futures_klines(symbol=SYMBOL, interval=EMA_INTERVAL, limit=ATR_PERIOD + 1)
        highs = np.array([float(k[2]) for k in klines])
        lows = np.array([float(k[3]) for k in klines])
        closes = np.array([float(k[4]) for k in klines])
        atr = talib.ATR(highs, lows, closes, timeperiod=ATR_PERIOD)[-1]

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
        client.futures_create_order(symbol=SYMBOL, side=tp_side, type=ORDER_TYPE_LIMIT,
                                    timeInForce=TIME_IN_FORCE_GTC, quantity=qty, price=str(tp_price), reduceOnly=True)
        logging.info(f"🎯 TP {tp_side} establecido en {tp_price}")
        client.futures_create_order(symbol=SYMBOL, side=sl_side, type="STOP_MARKET",
                                    stopPrice=str(sl_price), closePosition=True)
        logging.info(f"🛑 SL {sl_side} establecido en {sl_price} (ATR x2)")

        pos_actual = tipo
        return True

    except Exception as e:
        logging.error("❌ Error abriendo posición:", exc_info=True)
        return False


def resetear_delta():
    """Reinicia solo los datos del delta, sin el bucle infinito."""
    global ultima_senal, contador_senal, deltas_buffer, pos_actual

    logging.info("♻️ Reiniciando datos del DELTA por cambio de tendencia...")
    ultima_senal = None
    contador_senal = 0
    #pos_actual = None

    try:
        cargar_trades_iniciales()
        logging.info("✅ DELTA reiniciado y recalculado con trades iniciales.")
    except Exception:
        logging.error("❌ Error al reiniciar el DELTA:", exc_info=True)

# ===== DELTA SEGÚN VELA =====
def get_start_of_candle(interval_minutes, n_behind=0):
    """Devuelve timestamp UTC ms de inicio de la vela actual o n velas atrás."""
    now = datetime.now(timezone.utc)
    minutes_since_open = now.minute % interval_minutes
    candle_start = now - timedelta(minutes=minutes_since_open,
                                   seconds=now.second,
                                   microseconds=now.microsecond)
    candle_start -= timedelta(minutes=interval_minutes * n_behind)
    return int(candle_start.timestamp() * 1000)


def get_all_trades_for_candle(start_ts, end_ts):
    """
    Descarga todos los trades de Binance dentro de un rango de tiempo usando paginación.
    start_ts y end_ts en ms.
    """
    all_trades = []
    last_trade_id = None
    while True:
        params = {
            "symbol": SYMBOL,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 1000  # máximo permitido
        }
        if last_trade_id:
            params["fromId"] = last_trade_id + 1

        trades = client.futures_aggregate_trades(**params)
        if not trades:
            break

        all_trades.extend(trades)
        last_trade_id = trades[-1]["a"]

        # Si el último trade supera el end_ts, detener
        if trades[-1]["T"] > end_ts:
            break

        time.sleep(0.05)  # para no saturar API

    return all_trades


def cargar_trades_iniciales():
    """
    Carga los trades iniciales en el buffer usando timestamps de inicio de vela como claves.
    """
    global deltas_buffer, velas_cargadas
    deltas_buffer = {}
    velas_cargadas = False

    minutos = int(EMA_INTERVAL[:-1])
    ahora = int(datetime.now(timezone.utc).timestamp() * 1000)

    for i in range(VELAS_ATRAS, -1, -1):
        start_ts = get_start_of_candle(minutos, i)
        end_ts = ahora if i == 0 else get_start_of_candle(minutos, i - 1)

        try:
            trades = get_all_trades_for_candle(start_ts, end_ts)
        except Exception as e:
            logging.error(f"❌ Error cargando trades para vela {i}: {e}")
            trades = []

        # 🔹 Cambiar la clave de índice a timestamp de inicio de vela
        deltas_buffer[start_ts] = trades
        logging.info(
            f"✅ Cargada vela {i}: desde {datetime.fromtimestamp(start_ts/1000)} "
            f"hasta {datetime.fromtimestamp(end_ts/1000)} con {len(trades)} trades"
        )

    velas_cargadas = True



def calcular_delta_real_time(_delta_ignored=None):
    """
    Calcula el delta total combinando los deltas recientes de las últimas velas.
    """
    try:
        todos_deltas = []

        for trades in deltas_buffer.values():
            if trades and isinstance(trades[0], dict):
                for t in trades:
                    q = float(t.get("q", 0))
                    if t.get("m"):  # venta agresiva
                        q *= -1
                    todos_deltas.append(q)
            else:
                todos_deltas.extend(trades)

        total_delta = sum(todos_deltas)
        total_abs = sum(abs(x) for x in todos_deltas) or 1
        delta_pct = total_delta / total_abs * 100

        return delta_pct

    except Exception as e:
        logging.error(f"❌ Error en calcular_delta_real_time: {e}", exc_info=True)
        return 0


def on_message(ws, message):
    global ultima_senal, contador_senal, pos_actual, ultima_ema_ts, ultima_vela_timestamp
    try:
        data = json.loads(message)
        ws_price = float(data.get("p", 0))
        qty = float(data.get("q", 0))
        is_sell = data.get("m", False)

        #actualizar_trend(ws_price)  # <<--- AGREGA ESTA LÍNEA AQUÍ
        TrendWS.actualizar_trend(ws_price)

        precio = ws_price
        delta = -qty if is_sell else qty

        # Esperar hasta que las velas estén cargadas
        if not velas_cargadas:
            logging.info("⏳ Esperando a que las velas se carguen antes de procesar señales...")
            return

        # ================================
        # 🔄 ACTUALIZAR POSICIÓN ACTUAL
        # ================================
        pos_actual = pos_checker.pos_abierta
        logging.info(f"🔍 Posición cacheada por PositionChecker: {pos_actual}")

        # ====================================================
        # 🕒 DETECTAR CAMBIO DE VELA Y LIMPIAR DELTAS VIEJOS
        # ====================================================
        try:
            minutos = int(EMA_INTERVAL[:-1])
            now = datetime.utcnow().replace(second=0, microsecond=0)
            inicio_vela_actual = now - timedelta(minutes=now.minute % minutos)

            if "ultima_vela_timestamp" not in globals():
                ultima_vela_timestamp = inicio_vela_actual

            # Si la vela cambió, limpiamos los deltas viejos
            if inicio_vela_actual > ultima_vela_timestamp:
                ultima_vela_timestamp = inicio_vela_actual
                limpiar_deltas_viejos()
                logging.info(f"🕒 Nueva vela detectada: {inicio_vela_actual}. Buffer limpio.")

        except Exception as e:
            logging.error(f"Error al detectar cambio de vela: {e}")

        # ====================================================
        # ➕ AÑADIR TRADE AL BUFFER DE LA VELA ACTUAL
        # ====================================================
        # 🔹 Usar timestamp de inicio de vela actual como clave
        minutos = int(EMA_INTERVAL[:-1])
        now = datetime.utcnow().replace(second=0, microsecond=0)
        candle_start_ts = get_start_of_candle(minutos, 0)

        if deltas_buffer.get(candle_start_ts) is None:
            deltas_buffer[candle_start_ts] = []

        deltas_buffer[candle_start_ts].append({
            "q": qty,
            "m": is_sell
        })

        # ====================================================
        # 🧮 CÁLCULO DELTA DINÁMICO
        # ====================================================
        delta_pct = calcular_delta_real_time(0)  # delta pasado como 0, porque ya sumamos al buffer

        DELTA_DINAMICO_LONG = UMBRAL_PCT_FIJO
        DELTA_DINAMICO_SHORT = -UMBRAL_PCT_FIJO

        # ====================================================
        # 🔹 ACTUALIZAR EMA SI ES NECESARIO
        # ====================================================
        now_ts = datetime.now(timezone.utc)
        minuto_actual = now_ts.minute
        segundo_actual = now_ts.second

        # Solo recalcular al inicio exacto de una nueva vela (00 o 30 min)
        if (minuto_actual in [0, 30]) and (segundo_actual < 5):  # margen de 5s
            if not ultima_ema_ts or (now_ts - ultima_ema_ts).total_seconds() >= 1800:
                ema_handler.inicializar_ema()
                ultima_ema_ts = now_ts

        ema200 = float(ema_handler.get_ema())

        # ====================================================
        # 🔹 CALCULAR SAR
        # ====================================================
        closes, sar = obtener_sar_completo()
        sar_inicial = obtener_sar_inicial_real()
        sar_actual = sar[-1]  # último valor del SAR
        desviacion = calcular_desviacion(sar_inicial, sar_actual)

        # 🔹 Determinar tendencia actual

        #tendencia = "up" if sar_actual < closes[-1] else "down"
        #tendencia = "up" if sar[-2] < closes[-2] else "down"
        tendencia = "up" if sar[-1] < closes[-1] else "down"
        logging.info(
            f"🔹 Verificando tendencia: SAR[-1]={sar[-1]:.2f}, Close[-1]={closes[-1]:.2f}, "
            f"Tendencia calculada: {tendencia.upper()}"
        )

        # 🔁 Reiniciar limitador si cambió la tendencia
        #if limitador.tendencia_actual != tendencia:
        if limitador.tendencia_actual is not None and limitador.tendencia_actual != tendencia:
            limitador.reset()
            cerrar_todas()
            cancelar_ordenes_pendientes()
            #    ULTIMO CAMBIO
         #  resetear_delta()  # 🔹 Reinicia también el delta

        # 🧭 Actualizar el limitador con la nueva tendencia
        limitador.puede_abrir(tendencia)

        logging.info(
            f"📊 Δ={delta_pct:.2f}% | Umbral fijo={UMBRAL_PCT_FIJO:.2f}% | Precio={precio:.2f} | EMA200={ema200:.2f} | SAR={sar_actual:.2f} | Desv>1%={desviacion}"
        )
        # ====================================================
        # 📈 LÓGICA DE SEÑALES Y APERTURA DE OPERACIONES
        # ====================================================
        if pos_actual is None and ema200 is not None and precio > 0:

            # LONG
            if precio > ema200 and closes[-1] > sar[-1] and delta_pct >= DELTA_DINAMICO_LONG:
                if ultima_senal == "long":
                    contador_senal += 1
                else:
                    contador_senal = 1
                    ultima_senal = "long"

                if contador_senal >= CONSISTENT_SIGNALS:
                    tendencia_actual = "up"  # tendencia calculada según SAR
                    if TrendWS.trend_actual == "up":  # validar tendencia WS
                        if limitador.puede_abrir(tendencia_actual):
                            if not verificar_desviacion():
                                if abrir_posicion("long"):  # ✅ solo si se abre
                                    limitador.confirmar_apertura()
                            else:
                                logging.info("⚠️ Señal LONG descartada por bandera SAR (desviación > 1%)")
                        else:
                            logging.info("⚠️ Operación LONG limitada por TrendLimiter")
                    else:
                        logging.info(f"ℹ️ LONG descartado: micro tendencia actual '{TrendWS.trend_actual}' no coincide con SAR")
                    contador_senal = 0

            # SHORT
            elif precio < ema200 and closes[-1] < sar[-1] and delta_pct <= DELTA_DINAMICO_SHORT:
                if ultima_senal == "short":
                    contador_senal += 1
                else:
                    contador_senal = 1
                    ultima_senal = "short"

                if contador_senal >= CONSISTENT_SIGNALS:
                    tendencia_actual = "down"  # tendencia calculada según SAR
                    if TrendWS.trend_actual == "down":  # validar tendencia WS
                        if limitador.puede_abrir(tendencia_actual):
                            if not verificar_desviacion():
                                if abrir_posicion("short"):  # ✅ solo si se abre
                                    limitador.confirmar_apertura()
                            else:
                                logging.info("⚠️ Señal SHORT descartada por bandera SAR (desviación > 1%)")
                        else:
                            logging.info("⚠️ Operación SHORT limitada por TrendLimiter")
                    else:
                        logging.info(f"ℹ️ SHORT descartado: micro tendencia actual '{TrendWS.trend_actual}' no coincide con SAR")
                    contador_senal = 0



    except Exception:
        logging.error("❌ Error en on_message:", exc_info=True)


#####nuevo##############
def main():
    ema_handler.inicializar_ema()
    verificar_posiciones_abiertas()
    cargar_trades_iniciales()
    #threading.Thread(target=reset_bot_periodico, daemon=True).start()
    stream_url = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@trade"
    ws = websocket.WebSocketApp(stream_url, on_message=on_message)
    logging.info("🚀 Bot iniciado y escuchando trades en tiempo real...")
    ws.run_forever()

def iniciar_ws():
    """Inicia el WebSocket con reconexión automática sin reiniciar buffers."""
    url = f"wss://fstream.binance.com/ws/{SYMBOL.lower()}@trade"

    def on_open(ws):
        logging.info("🔗 WebSocket conectado con Binance")

    def on_error(ws, error):
        logging.error(f"❌ Error en WebSocket: {error}")
        ws.close()

    def on_close(ws, close_status_code, close_msg):
        logging.warning(f"⚠️ WebSocket cerrado ({close_status_code}): {close_msg}")
        logging.info("⏳ Esperando 5s para reconectar...")
        time.sleep(1)
        iniciar_ws()  # 🔁 reconexión sin reiniciar buffers

    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open
    )

    # correr en hilo separado para no bloquear
    hilo_ws = threading.Thread(target=ws.run_forever, kwargs={"ping_interval": 25, "ping_timeout": 20})
    hilo_ws.daemon = True
    hilo_ws.start()

    return ws


if __name__ == "__main__":
    logging.info("🚀 Iniciando bot principal...")
    ema_handler.inicializar_ema()
    verificar_posiciones_abiertas()

    if not velas_cargadas:
        cargar_trades_iniciales()  # solo la primera vez

    #iniciar_trend_ws(SYMBOL, interval_sec=5)
    iniciar_ws()  # lanza el WebSocket y mantiene buffers

    while True:
        time.sleep(1)