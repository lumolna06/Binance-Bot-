import time
import numpy as np
import talib
from binance.client import Client
from datetime import datetime
import logging

# ===== CONFIGURACIÓN =====
API_KEY = "TU_API_KEY"
API_SECRET = "TU_API_SECRET"
SYMBOL = "ETHUSDC"
INTERVAL = "30m"
KLIMIT = 1000       # Más velas para detectar tendencia real
SLEEP = 10
LIMITE_DESVIACION = 1.0  # Porcentaje

# ===== CONFIGURAR LOGGING =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ===== CLIENTE BINANCE =====
client = Client(API_KEY, API_SECRET)


def obtener_sar_completo():
    """Obtiene velas y calcula SAR completo."""
    klines = client.futures_klines(symbol=SYMBOL, interval=INTERVAL, limit=KLIMIT)
    highs = np.array([float(k[2]) for k in klines])
    lows = np.array([float(k[3]) for k in klines])
    closes = np.array([float(k[4]) for k in klines])
    sar = talib.SAR(highs, lows, acceleration=0.02, maximum=0.2)
    return closes, sar


def obtener_sar_inicial_real():
    """Detecta desde qué punto comenzó la tendencia actual según el SAR."""
    closes, sar = obtener_sar_completo()
    tendencia_actual = "up" if sar[-1] < closes[-1] else "down"

    # Buscar hacia atrás el punto donde el SAR cambió de lado
    for i in range(len(sar) - 2, 0, -1):
        if tendencia_actual == "up" and sar[i] > closes[i]:
            return sar[i + 1]  # SAR donde inició el cruce hacia abajo del precio
        elif tendencia_actual == "down" and sar[i] < closes[i]:
            return sar[i + 1]
    # Si no hay cambio encontrado, devuelve el primero disponible
    return sar[0]


def calcular_desviacion(sar_inicial, sar_actual):
    """Devuelve True si la desviación supera ±1%."""
    if sar_inicial == 0:
        return False
    desviacion = abs((sar_actual - sar_inicial) / sar_inicial * 100)
    logging.info(f"📊 SAR inicial real: {sar_inicial:.2f} | SAR actual: {sar_actual:.2f} | Desviación: {desviacion:.2f}%")
    return desviacion >= LIMITE_DESVIACION or desviacion <= -LIMITE_DESVIACION


def verificar_desviacion():
    """Función que puede llamarse desde otro archivo."""
    try:
        closes, sar = obtener_sar_completo()
        sar_inicial = obtener_sar_inicial_real()
        sar_actual = sar[-1]
        return calcular_desviacion(sar_inicial, sar_actual)
    except Exception as e:
        logging.error(f"❌ Error verificando desviación: {e}")
        return False


# ===== LOOP PRINCIPAL =====
if __name__ == "__main__":
    while True:
        try:
            es_desviacion = verificar_desviacion()
            logging.info(f"Desviación > {LIMITE_DESVIACION}%: {es_desviacion}")
            time.sleep(SLEEP)
        except Exception as e:
            logging.error(f"❌ Error: {e}")
            time.sleep(5)
