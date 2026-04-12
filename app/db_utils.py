# Ruta: GPS_Comercial/app/db_utils.py
"""Utilidades para auto-migrar la BD sin Alembic."""
import logging
from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def auto_add_missing_columns(db, app):
    """
    Detecta columnas faltantes en tablas existentes y las agrega.
    Seguro para correr multiples veces - solo agrega lo que falta.
    Solo funciona con tipos simples (String, Float, Integer, Boolean, Date, Text, DateTime).
    """
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        for table in db.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # db.create_all() se encarga de tablas nuevas

            existing_cols = {col['name'] for col in inspector.get_columns(table.name)}
            model_cols = {col.name: col for col in table.columns}

            for col_name, col in model_cols.items():
                if col_name not in existing_cols:
                    col_type = col.type.compile(dialect=engine.dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""

                    if col.default is not None:
                        if hasattr(col.default, 'arg'):
                            arg = col.default.arg
                            if isinstance(arg, str):
                                default = f"DEFAULT '{arg}'"
                            elif isinstance(arg, (int, float)):
                                default = f"DEFAULT {arg}"
                            elif isinstance(arg, bool):
                                default = f"DEFAULT {'true' if arg else 'false'}"

                    # Para columnas NOT NULL sin default, usar NULL temporalmente
                    if nullable == "NOT NULL" and not default:
                        nullable = "NULL"

                    sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col_name}" {col_type} {nullable} {default}'
                    try:
                        with engine.connect() as conn:
                            conn.execute(text(sql))
                            conn.commit()
                        logger.info("Columna agregada: %s.%s (%s)", table.name, col_name, col_type)
                    except Exception as e:
                        if 'already exists' in str(e).lower() or 'duplicate column' in str(e).lower():
                            pass  # Ya existe, OK
                        else:
                            logger.warning("No se pudo agregar %s.%s: %s", table.name, col_name, e)
