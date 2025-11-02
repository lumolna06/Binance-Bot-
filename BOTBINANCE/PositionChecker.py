# ===== PositionChecker.py =====
import threading
import time
import logging
from binance.client import Client

class PositionChecker:
    def __init__(self, client, symbol, intervalo=5):
        """
        :param client: instancia de binance.Client
        :param symbol: símbolo (ej. 'ETHUSDC')
        :param intervalo: segundos entre verificaciones
        """
        self.client = client
        self.symbol = symbol
        self.intervalo = intervalo
        self.pos_abierta = None  # 'long', 'short' o None
        self.running = False

    def verificar_posicion(self):
        """Consulta directamente en Binance si hay posición activa."""
        try:
            posiciones = self.client.futures_position_information(symbol=self.symbol)
            for p in posiciones:
                qty = float(p["positionAmt"])
                if qty != 0:
                    self.pos_abierta = "long" if qty > 0 else "short"
                    return True
            self.pos_abierta = None
            return False
        except Exception as e:
            logging.error("❌ Error verificando posición activa:", exc_info=True)
            return False

    def start_monitor(self):
        """Ejecuta verificación periódica en hilo separado."""
        if self.running:
            return
        self.running = True

        def loop():
            while self.running:
                self.verificar_posicion()
                time.sleep(self.intervalo)

        threading.Thread(target=loop, daemon=True).start()

    def stop_monitor(self):
        """Detiene el monitoreo."""
        self.running = False

    def hay_posicion_abierta(self):
        """Devuelve True/False según el último estado detectado."""
        return self.pos_abierta is not None
