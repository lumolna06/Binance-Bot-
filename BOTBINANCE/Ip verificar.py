import requests
import time

# ==== CONFIGURACIÓN TELEGRAM ====
BOT_TOKEN = "8374373396:AAGrVx2Da2WEhuURiWGQklmyeIy6Je3X3Jg"   # Token de tu bot de Telegram
CHAT_ID = "7826670887"       # Chat ID donde quieres recibir los mensajes

# ==== FUNCIONES ====

# Enviar mensaje a Telegram
def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

# Obtener la IP pública
def get_public_ip():
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=5)
        return response.json()["ip"]
    except:
        return None

# Monitorear la IP
def monitor_ip(intervalo_segundos=600):
    ip_actual = get_public_ip()
    print(f"IP inicial: {ip_actual}")
    send_telegram_message(f"[IP ALERT] 🟢 IP inicial detectada: {ip_actual}")

    while True:
        time.sleep(intervalo_segundos)
        nueva_ip = get_public_ip()
        if nueva_ip and nueva_ip != ip_actual:
            alerta = f"[IP ALERT] ⚠️ Cambio de IP detectado:\n{ip_actual} ➝ {nueva_ip}"
            print(alerta)
            send_telegram_message(alerta)
            ip_actual = nueva_ip
        else:
            print(f"Sin cambios. IP actual: {ip_actual}")

# ==== EJECUCIÓN ====
if __name__ == "__main__":
    monitor_ip(600)  # verifica cada 10 minutos