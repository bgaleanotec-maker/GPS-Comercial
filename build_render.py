"""Build script para Render - maneja migraciones de forma segura."""
import os
import subprocess
import sys

def run(cmd):
    """Ejecuta comando con ENABLE_BACKGROUND_WORKER=false."""
    env = os.environ.copy()
    env['ENABLE_BACKGROUND_WORKER'] = 'false'
    print(f">>> {cmd}")
    result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode

print("=== GPS Comercial Build ===")

# Intentar upgrade normal
print("Aplicando migraciones...")
code = run("flask db upgrade")

if code != 0:
    print("Primer intento fallo. Haciendo stamp head...")
    run("flask db stamp head")
    print("Re-intentando upgrade...")
    run("flask db upgrade")

print("=== Build completado ===")
sys.exit(0)
