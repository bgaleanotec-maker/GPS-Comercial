#!/usr/bin/env bash
# Instala la copia semanal de Traccar en el servidor (ejecutar como root una sola vez).
#   1) copia traccar-backup.sh a /opt/traccar-backups
#   2) programa cron: domingos 03:00 hora del servidor
#   3) autoriza la llave SSH del PC de respaldo (solo lectura de /opt/traccar-backups)
#   4) hace la primera copia de inmediato
# No toca la base de datos de Traccar (solo se lee al hacer la copia).
set -euo pipefail

PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEDV+IODRrZkiFf7x+8QDcirI1jxJjZ35QusAdP3dBCv vantigo-backup@bgale-pc'
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "== Instalando copia semanal de Traccar =="
mkdir -p /opt/traccar-backups
install -m 750 "$SRC/traccar-backup.sh" /opt/traccar-backups/traccar-backup.sh
echo "Script copiado a /opt/traccar-backups/traccar-backup.sh"

# Cron semanal (sin duplicar si ya existe; el servidor puede no tener crontab aun)
CRON_LINE="0 3 * * 0 /opt/traccar-backups/traccar-backup.sh >> /opt/traccar-backups/cron.log 2>&1"
{ crontab -l 2>/dev/null | grep -v 'traccar-backup.sh' || true; echo "$CRON_LINE"; } | crontab -
echo "Cron instalado: domingos 03:00"

# Llave del PC (para que el PC descargue las copias con scp)
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
grep -qF "$PUBKEY" /root/.ssh/authorized_keys || echo "$PUBKEY" >> /root/.ssh/authorized_keys
echo "Llave SSH del PC autorizada"

# Herramientas de volcado segun el motor (si aplica)
if grep -q "mysql\|mariadb" /opt/traccar/conf/traccar.xml 2>/dev/null && ! command -v mysqldump >/dev/null; then
  apt-get update -qq && apt-get install -y -qq mysql-client >/dev/null 2>&1 || apt-get install -y -qq mariadb-client >/dev/null 2>&1 || true
fi
if grep -q "postgresql" /opt/traccar/conf/traccar.xml 2>/dev/null && ! command -v pg_dump >/dev/null; then
  apt-get update -qq && apt-get install -y -qq postgresql-client >/dev/null 2>&1 || true
fi

echo "Primera copia..."
/opt/traccar-backups/traccar-backup.sh
ls -lh /opt/traccar-backups/
