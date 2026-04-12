#!/bin/bash
# Script de build para Render - maneja primer deploy y migraciones
set -e

echo "=== GPS Comercial Build ==="

# Instalar dependencias
pip install -r requirements.txt

# Intentar aplicar migraciones
# Si falla (primer deploy, BD sin alembic_version), hacer stamp head primero
echo "Aplicando migraciones..."
flask db upgrade 2>/dev/null || {
    echo "Primera ejecucion detectada. Marcando BD existente..."
    flask db stamp head
    flask db upgrade
}

echo "=== Build completado ==="
