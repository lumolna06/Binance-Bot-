import requests
import time
import os

SYMBOL = "ETHUSDC"
LIMIT = 100
THRESHOLD_PERCENT = 5
REFRESH_INTERVAL = 5  # segundos

def get_order_book(symbol, limit=100):
    url = f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit={limit}"
    return requests.get(url).json()

def detectar_paredes(ordenes, lado="compra", umbral=5):
    total_volumen = sum(float(o[1]) for o in ordenes)
    paredes = []
    for precio, cantidad in ordenes:
        porcentaje = (float(cantidad) / total_volumen) * 100
        if porcentaje >= umbral:
            paredes.append({
                "lado": lado,
                "precio": float(precio),
                "cantidad": float(cantidad),
                "porcentaje": round(porcentaje, 2)
            })
    return paredes

def mostrar_paredes(paredes_compra, paredes_venta):
    os.system('cls' if os.name == 'nt' else 'clear')  # limpia la consola
    print(f"\n📊 Análisis del Order Book en tiempo real: {SYMBOL}")
    print(f"Actualizado cada {REFRESH_INTERVAL}s\n")

    if paredes_compra:
        print("🟢 PAREDES DE COMPRA:")
        for p in paredes_compra:
            print(f"  Precio: {p['precio']:.2f} | Cantidad: {p['cantidad']:.4f} | {p['porcentaje']}% del total de compras")
    else:
        print("🟢 No se detectaron paredes de compra significativas.")

    if paredes_venta:
        print("\n🔴 PAREDES DE VENTA:")
        for p in paredes_venta:
            print(f"  Precio: {p['precio']:.2f} | Cantidad: {p['cantidad']:.4f} | {p['porcentaje']}% del total de ventas")
    else:
        print("\n🔴 No se detectaron paredes de venta significativas.")

def main():
    while True:
        try:
            data = get_order_book(SYMBOL, LIMIT)
            bids = data['bids']
            asks = data['asks']
            paredes_compra = detectar_paredes(bids, "compra", THRESHOLD_PERCENT)
            paredes_venta  = detectar_paredes(asks, "venta",  THRESHOLD_PERCENT)
            mostrar_paredes(paredes_compra, paredes_venta)
            time.sleep(REFRESH_INTERVAL)
        except KeyboardInterrupt:
            print("\n⏹️ Monitoreo detenido por el usuario.")
            break
        except Exception as e:
            print("⚠️ Error:", e)
            time.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    main()
