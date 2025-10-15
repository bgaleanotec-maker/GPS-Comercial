# Ruta: SST/test_traccar.py

# Este es un script de prueba para conectar directamente a Traccar sin usar Flask.
import requests

# --- CONFIGURACIÓN ---
# Por favor, verifica que estos datos sean EXACTAMENTE los mismos que tienes en config.py
TRACCAR_URL = 'http://68.183.171.26:8082'  # <-- ¡USA TU IP!
TRACCAR_USER = 'admin'                    # <-- Usuario de Traccar
TRACCAR_PASSWORD = 'admin'                # <-- Contraseña de Traccar

print("\n--- INICIANDO PRUEBA DE CONEXIÓN DIRECTA A TRACCAR ---\n")
print(f"URL de la API: {TRACCAR_URL}/api/devices")
print(f"Usuario: {TRACCAR_USER}")

try:
    # Hacemos la llamada a la API de Traccar
    response = requests.get(
        f"{TRACCAR_URL}/api/devices",
        auth=(TRACCAR_USER, TRACCAR_PASSWORD)
    )

    # Imprimimos los resultados de la prueba
    print(f"\n--- RESULTADOS ---")
    print(f"Código de estado recibido: {response.status_code}")
    print(f"Respuesta del servidor (texto): {response.text}")
    print("------------------\n")

    if response.status_code == 200:
        print("¡ÉXITO! La conexión con Traccar funciona y se recibió una respuesta correcta.")
        try:
            devices = response.json()
            print(f"Se encontraron {len(devices)} dispositivo(s).")
            # Imprimimos los nombres de los dispositivos para confirmar
            for device in devices:
                print(f" - Dispositivo: {device.get('name')}, ID: {device.get('id')}")
        except requests.exceptions.JSONDecodeError:
            print("ERROR: La respuesta no es un JSON válido, aunque el estado fue 200.")
    else:
        print("FALLO: La conexión no fue exitosa. Revisa el código de estado y la respuesta para encontrar la causa.")
        if response.status_code == 401:
            print("POSIBLE CAUSA: El código 401 significa 'No autorizado'. Las credenciales (usuario/contraseña) son incorrectas.")
        elif response.status_code == 404:
            print("POSIBLE CAUSA: El código 404 significa 'No encontrado'. La URL de la API es incorrecta.")
        else:
            print(f"POSIBLE CAUSA: Revisa el significado del código de estado {response.status_code} para más información.")

except requests.exceptions.RequestException as e:
    print("\n--- ¡ERROR DE CONEXIÓN! ---")
    print(f"No se pudo establecer una conexión con el servidor de Traccar.")
    print(f"Detalle del error: {e}")
    print("POSIBLES CAUSAS:")
    print("1. El servidor de Traccar no está funcionando.")
    print("2. La TRACCAR_URL es incorrecta (¿es http o https? ¿El puerto es correcto?).")
    print("3. Un firewall está bloqueando la conexión desde tu computadora al servidor.")