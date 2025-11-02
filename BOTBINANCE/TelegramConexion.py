# monitor_binance_telegram.py
import asyncio
from datetime import datetime
from binance.client import Client
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class MonitorBinanceTelegram:
    def __init__(self, binance_api_key, binance_api_secret, telegram_token, chat_id):
        self.client = Client(binance_api_key, binance_api_secret)
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.app = ApplicationBuilder().token(telegram_token).build()

        # Handlers de comandos
        self.app.add_handler(CommandHandler("saldo", self.comando_saldo))
        self.app.add_handler(CommandHandler("historico", self.comando_historico))

        # Control de operaciones detectadas
        self.ultima_operacion_id = None

    # === 1️⃣ Monitorear automáticamente nuevas operaciones ===
    async def monitorear_operaciones(self):
        while True:
            try:
                trades = self.client.futures_account_trades(limit=1)
                if trades:
                    last_trade = trades[-1]
                    trade_id = last_trade["id"]

                    if trade_id != self.ultima_operacion_id:
                        self.ultima_operacion_id = trade_id
                        pnl = float(last_trade.get("realizedPnl", 0))
                        comision = -abs(float(last_trade.get("commission", 0)))
                        total = pnl + comision
                        simbolo = last_trade["symbol"]

                        # Verificar si la posición está cerrada completamente
                        posiciones = self.client.futures_position_information(symbol=simbolo)
                        if posiciones:
                            pos_size = float(posiciones[0]["positionAmt"])
                        else:
                            pos_size = 0

                        if pos_size == 0 and total != 0:
                            # Cierre completo
                            mensaje = (
                                f"✅ *Operación cerrada*\n\n"
                                f"Símbolo: {simbolo}\n"
                                f"PnL: {pnl:.4f}\n"
                                f"Comisión: {comision:.4f}\n"
                                f"💵 Resultado real: {total:.4f}\n"
                                f"🕓 {datetime.fromtimestamp(last_trade['time'] / 1000)}"
                            )
                        else:
                            # Nueva apertura o ajuste parcial
                            mensaje = (
                                f"📊 *Nueva operación detectada*\n\n"
                                f"Símbolo: {simbolo}\n"
                                f"Tipo: {'BUY' if last_trade['side'] == 'BUY' else 'SELL'}\n"
                                f"Precio: {last_trade['price']}\n"
                                f"Cantidad: {last_trade['qty']}\n"
                                f"PnL: {pnl:.4f}\n"
                                f"Comisión: {comision:.4f}\n"
                                f"💵 Resultado real: {total:.4f}\n"
                                f"🕓 {datetime.fromtimestamp(last_trade['time'] / 1000)}"
                            )

                        await self.app.bot.send_message(chat_id=self.chat_id, text=mensaje, parse_mode="Markdown")

            except Exception as e:
                print(f"⚠️ Error monitoreando operaciones: {e}")

            await asyncio.sleep(10)  # cada 10 segundos revisa si hay nuevas

    # === 2️⃣ Comando /saldo ===
    async def comando_saldo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            balances = self.client.futures_account_balance()
            texto = "💰 *Saldos Futuros:*\n\n"
            for b in balances:
                asset = b["asset"]
                balance = float(b["balance"])
                if balance != 0:
                    texto += f"{asset}: {balance:.4f}\n"
            await update.message.reply_text(texto, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error al obtener saldo: {e}")

    # === 3️⃣ Comando /historico X ===
    async def comando_historico(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            cantidad = int(context.args[0]) if context.args else 2
        except:
            await update.message.reply_text("Uso: /historico <número>")
            return

        try:
            trades = self.client.futures_account_trades(limit=cantidad)
            if not trades:
                await update.message.reply_text("No se encontraron operaciones recientes.")
                return

            texto = f"📜 *Últimas {cantidad} operaciones:*\n"
            total_real = 0
            for t in trades[-cantidad:]:
                pnl = float(t.get("realizedPnl", 0))
                comision = -abs(float(t.get("commission", 0)))  # ahora siempre negativa
                total_real += pnl + comision
                texto += (
                    f"\n{t['symbol']} | {'BUY' if t['side'] == 'BUY' else 'SELL'}\n"
                    f"PnL: {pnl:.4f} | Comisión: {comision:.4f} | "
                    f"Real: {pnl + comision:.4f}"
                )

            texto += f"\n\n💵 *Total real: {total_real:.4f}*"
            await update.message.reply_text(texto, parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text(f"⚠️ Error al obtener historial: {e}")

    # === 4️⃣ Ejecutar el monitor ===
    def run(self):
        print("🚀 Monitor Binance + Telegram iniciado")
        loop = asyncio.get_event_loop()
        loop.create_task(self.monitorear_operaciones())
        self.app.run_polling()

# === Ejecutar directamente ===
if __name__ == "__main__":
    TELEGRAM_TOKEN = "8430210865:AAFB7t0aIiJQiFNDHBwFQWN4kJXG4Ksfd0M"
    CHAT_ID = 7826670887  # tu chat ID
    BINANCE_API_KEY = "KNOHovcOWEDLeQkXh6xT27ZEwGnNN9r1kkBpefE36tgGpG7MyN7XjYv99byJG1xp"
    BINANCE_API_SECRET = "81Q1smIhahcj7XjgJDfJwcp7v3mbb4MvQaLg42mF3R0TJO25GZxRO84j6g6MDOMZ"

    monitor = MonitorBinanceTelegram(
        BINANCE_API_KEY,
        BINANCE_API_SECRET,
        TELEGRAM_TOKEN,
        CHAT_ID
    )
    monitor.run()

