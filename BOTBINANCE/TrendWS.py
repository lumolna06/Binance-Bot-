# TrendWS.py
from collections import deque
from datetime import datetime
import logging

trend_actual = "flat"  # variable global compartida
precios_recientes = deque()  # buffer de precios para micro-tendencia

# Configuración del intervalo para cálculo de micro-tendencia (segundos)
INTERVAL_SEC = 5
CAMBIO_PCT = 0.03  # porcentaje mínimo para considerar up/down

def actualizar_trend(precio: float):
    """
    Recibe el precio actual y calcula la micro-tendencia.
_    Actualiza la variable global `trend_actual`.
    """
    global trend_actual, precios_recientes

    if precio <= 0:
        return

    ts = datetime.utcnow()
    precios_recientes.append((ts, precio))

    # Limpiar precios antiguos
    while precios_recientes and (ts - precios_recientes[0][0]).total_seconds() > INTERVAL_SEC:
        precios_recientes.popleft()

    if len(precios_recientes) >= 2:
        start_price = precios_recientes[0][1]
        end_price = precios_recientes[-1][1]

        if start_price == 0:
            return

        change_percent = (end_price - start_price) / start_price * 100

        if change_percent > CAMBIO_PCT:
            trend_actual = "up"
        elif change_percent < -CAMBIO_PCT:
            trend_actual = "down"
        else:
            trend_actual = "flat"

    logging.info(f"[{ts.strftime('%H:%M:%S')}] Precio: {precio:.2f} | Micro Tendencia: {trend_actual}")
