# Copias de seguridad de Traccar (servidor DigitalOcean 64.227.85.213)

La base de Traccar (usuarios, dispositivos, posiciones, geocercas) es el corazón de VantiGo.
Este paquete deja **tres capas** de respaldo, ninguna toca ni borra la base original:

| Capa | Dónde | Frecuencia | Qué cubre |
|---|---|---|---|
| 1. Copia lógica en el servidor | `/opt/traccar-backups/` (últimas 8) | Domingos 03:00 (cron) | BD + `conf/traccar.xml` + `media/` |
| 2. Copia en el PC / OneDrive | `C:\Users\bgale\OneDrive\Traccar_Backups\` (últimas 12) | Domingos 07:00 (Tarea programada) | La misma copia, verificada con SHA-256, y sincronizada a OneDrive |
| 3. (Opcional, de pago) Backups de DigitalOcean | Panel DO → Droplet → Backups | Semanal automático | Imagen completa del servidor (restaura todo en minutos) |

## Instalación (una sola vez)

### A. En el servidor (consola del Droplet en DigitalOcean o SSH)
1. Panel DigitalOcean → Droplet de Traccar → **Access** → **Launch Droplet Console** (entra como root).
2. Copiar el contenido de `traccar-backup.sh` e `install-on-server.sh` al servidor, por ejemplo:
   ```bash
   mkdir -p /root/vantigo && cd /root/vantigo
   nano traccar-backup.sh      # pegar el contenido, Ctrl+O, Enter, Ctrl+X
   nano install-on-server.sh   # pegar el contenido, Ctrl+O, Enter, Ctrl+X
   bash install-on-server.sh
   ```
   El instalador: programa el cron semanal, autoriza la llave SSH del PC (solo esa llave) y hace la **primera copia de inmediato**.
3. Verificar: `ls -lh /opt/traccar-backups/` debe mostrar `traccar-backup-AAAAMMDD-HHMMSS.tar.gz` y `latest.tar.gz`.

> Motor H2 (el de Traccar por defecto): la copia pausa el servicio ~5–10 s para copiar el archivo de forma consistente y lo reinicia siempre (incluso si algo falla). Los GPS reenvían las posiciones que no alcanzaron a entregar. Con MySQL/PostgreSQL no hay pausa (`mysqldump --single-transaction` / `pg_dump`).

### B. En el PC (PowerShell, una vez)
```powershell
cd "C:\Users\bgale\OneDrive\GPS_Comercial\ops\traccar-backup"
.\pull-backup.ps1        # primera descarga manual (prueba la conexión)
.\register-task.ps1      # deja la descarga semanal programada
```
La llave privada usada es `C:\Users\bgale\.ssh\vantigo_traccar` (no compartirla). Su pública ya está dentro de `install-on-server.sh`.

## Restaurar (si hay que volver a desplegar Traccar sin perder usuarios ni registros)
1. Instalar Traccar de la **misma versión** (hoy 5.12) en el servidor nuevo: `https://www.traccar.org/download/`.
2. `systemctl stop traccar`
3. Descomprimir la copia: `mkdir /root/restore && tar -xzf traccar-backup-XXXX.tar.gz -C /root/restore`
4. Según el motor:
   - **H2**: `cp -a /root/restore/db/. /opt/traccar/data/`
   - **MySQL**: `zcat /root/restore/db/traccar.sql.gz | mysql -u USUARIO -p traccar`
   - **PostgreSQL**: `pg_restore -U USUARIO -d traccar /root/restore/db/traccar.dump`
5. `cp /root/restore/conf/traccar.xml /opt/traccar/conf/` y `cp -a /root/restore/media /opt/traccar/` (si existe)
6. `systemctl start traccar` → entrar a `http://IP:8082` con los usuarios de siempre.
7. Si cambia la IP, actualizar `TRACCAR_URL` en Render (servicio gps-comercial) y la IP en los dispositivos GPS.

## Comprobación mensual sugerida
- `tail /opt/traccar-backups/backup.log` en el servidor (línea "OK ->" de cada domingo).
- `C:\Users\bgale\OneDrive\Traccar_Backups\pull.log` en el PC.
