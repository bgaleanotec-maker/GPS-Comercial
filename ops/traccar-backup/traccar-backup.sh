#!/usr/bin/env bash
# =====================================================================
#  VantiGo - Copia de seguridad de Traccar (SOLO LECTURA sobre la BD)
#
#  Genera un .tar.gz con:
#    - la base de datos (H2: archivo database.mv.db | MySQL: mysqldump | Postgres: pg_dump)
#    - /opt/traccar/conf  (traccar.xml con usuarios/claves de BD, puertos, etc.)
#    - /opt/traccar/media (fotos/archivos adjuntos si existen)
#  Guarda las copias en /opt/traccar-backups y conserva las ultimas KEEP.
#  NUNCA borra ni modifica la base de datos: solo la lee y la copia.
#
#  Uso:  sudo /opt/traccar-backups/traccar-backup.sh
#  Cron: se instala con install-on-server.sh (domingos 03:00)
# =====================================================================
set -euo pipefail

TRACCAR_DIR="${TRACCAR_DIR:-/opt/traccar}"
BACKUP_DIR="${BACKUP_DIR:-/opt/traccar-backups}"
KEEP="${KEEP:-8}"                       # semanas que se conservan en el servidor
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$BACKUP_DIR/tmp-$STAMP"
OUT="$BACKUP_DIR/traccar-backup-$STAMP.tar.gz"
LOG="$BACKUP_DIR/backup.log"
CONF="$TRACCAR_DIR/conf/traccar.xml"

mkdir -p "$BACKUP_DIR" "$WORK/db"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# --- Detectar motor de base de datos desde traccar.xml ---------------------
get_entry() { sed -n "s|.*<entry key='$1'>\(.*\)</entry>.*|\1|p; s|.*<entry key=\"$1\">\(.*\)</entry>.*|\1|p" "$CONF" | head -1; }
DB_URL="$(get_entry database.url || true)"
DB_USER="$(get_entry database.user || true)"
DB_PASS="$(get_entry database.password || true)"
log "Inicio copia. url=${DB_URL:-<h2 por defecto>}"

STOPPED=0
case "$DB_URL" in
  *mysql*|*mariadb*)
    # Sin detener Traccar: volcado consistente en una transaccion
    HOST="$(echo "$DB_URL" | sed -n 's|.*//\([^:/?]*\).*|\1|p')"; PORT="$(echo "$DB_URL" | sed -n 's|.*//[^:/]*:\([0-9]*\).*|\1|p')"
    DBN="$(echo "$DB_URL" | sed -n 's|.*/\([^/?]*\)\(?.*\)\?$|\1|p')"
    log "MySQL: host=${HOST:-localhost} db=$DBN"
    MYSQL_PWD="$DB_PASS" mysqldump --single-transaction --quick --routines --triggers \
      -h "${HOST:-localhost}" -P "${PORT:-3306}" -u "$DB_USER" "$DBN" | gzip > "$WORK/db/$DBN.sql.gz"
    ;;
  *postgresql*)
    HOST="$(echo "$DB_URL" | sed -n 's|.*//\([^:/?]*\).*|\1|p')"; PORT="$(echo "$DB_URL" | sed -n 's|.*//[^:/]*:\([0-9]*\).*|\1|p')"
    DBN="$(echo "$DB_URL" | sed -n 's|.*/\([^/?]*\)\(?.*\)\?$|\1|p')"
    log "PostgreSQL: host=${HOST:-localhost} db=$DBN"
    PGPASSWORD="$DB_PASS" pg_dump -h "${HOST:-localhost}" -p "${PORT:-5432}" -U "$DB_USER" -Fc "$DBN" > "$WORK/db/$DBN.dump"
    ;;
  *)
    # H2 (por defecto en Traccar): el archivo esta abierto por el servicio; para una
    # copia 100% consistente se pausa Traccar unos segundos (los GPS reenvian lo
    # que no alcanzaron a entregar). Se reinicia SIEMPRE, incluso si algo falla.
    log "H2: copiando $TRACCAR_DIR/data"
    if systemctl is-active --quiet traccar; then
      systemctl stop traccar; STOPPED=1
      trap 'systemctl start traccar' EXIT
      sleep 3
    fi
    cp -a "$TRACCAR_DIR/data/." "$WORK/db/"
    if [ "$STOPPED" = 1 ]; then systemctl start traccar; trap - EXIT; STOPPED=0; fi
    ;;
esac

# --- Configuracion y adjuntos --------------------------------------------
cp -a "$TRACCAR_DIR/conf" "$WORK/conf"
[ -d "$TRACCAR_DIR/media" ] && cp -a "$TRACCAR_DIR/media" "$WORK/media" || true
cat > "$WORK/INFO.txt" <<EOF
Copia de seguridad Traccar - $(date)
Servidor: $(hostname) ($(hostname -I 2>/dev/null | awk '{print $1}'))
Version Traccar: $(ls "$TRACCAR_DIR"/lib/tracker-server*.jar 2>/dev/null | head -1 || echo desconocida)
Motor BD: ${DB_URL:-H2 (archivo data/database.mv.db)}
Contenido: db/ (base de datos), conf/ (traccar.xml), media/ (adjuntos)
Restaurar: ver README.md (ops/traccar-backup) en el repositorio GPS-Comercial
EOF

tar -C "$WORK" -czf "$OUT" .
rm -rf "$WORK"
SIZE="$(du -h "$OUT" | cut -f1)"
sha256sum "$OUT" > "$OUT.sha256"
ln -sfn "$OUT" "$BACKUP_DIR/latest.tar.gz"
ln -sfn "$OUT.sha256" "$BACKUP_DIR/latest.tar.gz.sha256"
log "OK -> $OUT ($SIZE)"

# --- Rotacion: solo se borran COPIAS ANTIGUAS de este directorio, nunca la BD ---
{ ls -1t "$BACKUP_DIR"/traccar-backup-*.tar.gz 2>/dev/null || true; } | tail -n +$((KEEP + 1)) | while read -r f; do
  rm -f "$f" "$f.sha256"; log "rotada: $(basename "$f")"
done
exit 0
