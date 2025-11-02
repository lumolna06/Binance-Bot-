import logging
from logging.handlers import TimedRotatingFileHandler
import os
import requests
import sys

class TelegramHandler(logging.Handler):
    """Handler personalizado que envía logs a Telegram cuando son de nivel ERROR o superior."""
    def __init__(self, bot_token, chat_id):
        super().__init__(level=logging.ERROR)
        self.bot_token = bot_token
        self.chat_id = chat_id

    def emit(self, record):
        try:
            log_entry = self.format(record)
            mensaje = f"🚨 *Error crítico en el bot:*\n```\n{log_entry}\n```"
            requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                data={"chat_id": self.chat_id, "text": mensaje, "parse_mode": "Markdown"}
            )
        except Exception:
            pass


class LoggerConfig:
    @staticmethod
    def configurar_logger(carpeta="logs", dias_guardados=7,
                          telegram_token=None, telegram_chat_id=None):
        """
        Configura el logger raíz para que capture todos los logging.info/error,
        guarde logs en archivo, muestre en consola y envíe errores a Telegram.
        """
        os.makedirs(carpeta, exist_ok=True)
        log_file = os.path.join(carpeta, "bot_log.log")

        # 🔹 Formato de salida
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        # 🔹 Handler rotativo diario (archivo)
        file_handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=dias_guardados,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)

        # 🔹 Handler de consola
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)

        # 🔹 Logger raíz
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Limpiar handlers antiguos para evitar duplicados
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)

        # Añadir handlers
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

        # 🔹 Handler de Telegram (opcional)
        if telegram_token and telegram_chat_id:
            telegram_handler = TelegramHandler(telegram_token, telegram_chat_id)
            telegram_handler.setFormatter(formatter)
            root_logger.addHandler(telegram_handler)
            logging.info("📲 Notificaciones de errores activadas en Telegram.")

        logging.info("🚀 Logger inicializado (archivo, consola y Telegram).")

        return root_logger
