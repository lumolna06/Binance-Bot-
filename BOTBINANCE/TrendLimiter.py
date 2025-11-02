# ===== TrendLimiter.py =====
import logging

class TrendLimiter:
    def __init__(self, max_ops_por_tendencia=1):
        self.max_ops = max_ops_por_tendencia
        self.tendencia_actual = None
        self.contador = 0

    def puede_abrir(self, tendencia):
        """Devuelve True si se puede intentar abrir, sin aumentar el contador aún."""
        if self.tendencia_actual != tendencia:
            logging.info(f"♻️ Tendencia cambió de {self.tendencia_actual} a {tendencia}. Reiniciando contador.")
            self.tendencia_actual = tendencia
            self.contador = 0

        logging.info(f"🔸 Tendencia actual: {self.tendencia_actual} | Operaciones en esta tendencia: {self.contador}/{self.max_ops}")

        if self.contador < self.max_ops:
            return True
        else:
            logging.info(f"⚠️ Límite de operaciones alcanzado en tendencia {tendencia} ({self.max_ops})")
            return False

    def confirmar_apertura(self):
        """Aumenta el contador solo cuando la operación realmente se abrió."""
        self.contador += 1
        logging.info(f"🔹 Operación confirmada {self.contador}/{self.max_ops} en tendencia {self.tendencia_actual}")

    def reset(self):
        self.tendencia_actual = None
        self.contador = 0
