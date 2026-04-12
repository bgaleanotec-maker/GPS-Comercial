# Ruta: GPS_Comercial/run.py
from app import create_app

app = create_app()

if __name__ == '__main__':
    from waitress import serve
    print("\n--- INICIANDO SERVIDOR WEB CON WAITRESS ---")
    print("Servidor corriendo en http://127.0.0.1:5000")
    print("-----------------------------------------\n")
    serve(app, host='127.0.0.1', port=5000)
