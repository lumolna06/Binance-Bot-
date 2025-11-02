import logging
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from binance.client import Client

getcontext().prec = 18

class EMARealtime:
    def __init__(self, client: Client, symbol: str, interval='1h', length=200, data_limit=15000):
        self.client = client
        self.symbol = symbol
        self.interval = interval
        self.length = length
        self.data_limit = data_limit
        self.alpha = Decimal('2') / Decimal(length + 1)
        self.ema = None
        self.last_update = None
        self.initialized = False

    def inicializar_ema(self):
        """Descarga datos históricos y calcula la EMA inicial con precisión alta."""
        try:
            logging.info(f"⏳ Descargando {self.data_limit} velas para inicializar EMA{self.length}...")
            klines = self.client.futures_klines(symbol=self.symbol, interval=self.interval, limit=self.data_limit)
            closes = [Decimal(k[4]) for k in klines]  # precio de cierre
            ema = closes[0]
            for price in closes[1:]:
                ema = (price - ema) * self.alpha + ema
            self.ema = ema
            self.last_update = datetime.now(timezone.utc)
            self.initialized = True
            logging.info(f"✅ EMA inicializada: {self.ema:.8f}")
        except Exception as e:
            logging.error(f"❌ Error inicializando EMA: {e}", exc_info=True)

    def actualizar_por_trade(self, price):
        if not self.initialized:
            raise ValueError("EMA no inicializada. Llama a inicializar_ema() primero.")
        price = Decimal(price)
        self.ema = (price - self.ema) * self.alpha + self.ema
        self.last_update = datetime.now(timezone.utc)
        return self.ema

    def get_ema(self):
        if not self.initialized:
            raise ValueError("EMA no inicializada.")
        return self.ema
