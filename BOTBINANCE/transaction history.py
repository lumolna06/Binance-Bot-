import pandas as pd
from binance.client import Client
from datetime import datetime

# ===== CONFIGURACIÓN =====
API_KEY = "KNOHovcOWEDLeQkXh6xT27ZEwGnNN9r1kkBpefE36tgGpG7MyN7XjYv99byJG1xp"
API_SECRET = "81Q1smIhahcj7XjgJDfJwcp7v3mbb4MvQaLg42mF3R0TJO25GZxRO84j6g6MDOMZ"
LIMIT = 1000  # Cantidad de operaciones por símbolo

# ===== CONEXIÓN A FUTUROS USDT-M =====
client = Client(API_KEY, API_SECRET)
futures_client = client.futures_account_trades  # método directo para trades de futuros

# ===== OBTENER TODOS LOS SÍMBOLOS OPERADOS EN FUTUROS =====
print("🔍 Obteniendo lista de símbolos con operaciones en Futuros USDT-M...")
exchange_info = client.futures_exchange_info()
symbols = [s["symbol"] for s in exchange_info["symbols"] if s["contractType"] == "PERPETUAL"]

todos_trades = []

# ===== DESCARGAR HISTORIAL =====
for symbol in symbols:
    try:
        trades = futures_client(symbol=symbol, limit=LIMIT)
        if trades:
            for t in trades:
                t["symbol"] = symbol
            todos_trades.extend(trades)
            print(f"✅ {len(trades)} trades obtenidos de {symbol}")
    except Exception:
        # Algunos símbolos no tienen historial, ignoramos
        pass

# ===== PROCESAR Y GUARDAR =====
if not todos_trades:
    print("⚠️ No se encontraron operaciones en Futuros.")
else:
    df = pd.DataFrame(todos_trades)

    # Limpiamos y convertimos tipos
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    columnas = [
        "symbol", "orderId", "id", "price", "qty", "realizedPnl",
        "marginAsset", "commission", "commissionAsset", "buyer", "maker", "time", "positionSide"
    ]
    df = df[[c for c in columnas if c in df.columns]]

    # Convertir numéricos
    for col in ["price", "qty", "realizedPnl", "commission"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Exportar a Excel
    nombre_archivo = f"historial_futuros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(nombre_archivo, index=False)
    print(f"\n📊 Archivo Excel generado correctamente: {nombre_archivo}")
