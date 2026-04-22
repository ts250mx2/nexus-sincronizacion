import decimal
import logging
from datetime import datetime

def valida_nulo(value, is_string=False):
    """
    Simulates the VB6 ValidaNulos function.
    Returns default values (0 or '') for None/Null values.
    """
    if value is None:
        return "NULL"
    
    if is_string:
        # Escape single quotes and wrap in quotes
        val = str(value).replace("'", "''")
        return f"'{val}'"
    
    if isinstance(value, (int, float, decimal.Decimal)):
        return str(value)
    
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    
    if isinstance(value, bool):
        return "1" if value else "0"
        
    return str(value)

def format_sql_date(date_val):
    """
    Formats a date for SQL queries.
    """
    if not date_val:
        return "2000-01-01 00:00:00"
    if isinstance(date_val, str):
        return date_val
    return date_val.strftime('%Y-%m-%d %H:%M:%S')

def campo_requerido(cursor, sql, field_name):
    """
    Fetches a single value from a query.
    Simulates the VB6 CampoRequerido function.
    """
    try:
        cursor.execute(sql)
    except Exception as e:
        logging.error(f"Error en campo_requerido: {e}")
        logging.error(f"SQL: {sql}")
        raise
        
    row = cursor.fetchone()
    if row:
        # 1. Intentar acceso como diccionario (común en mysql-connector con dictionary=True)
        if isinstance(row, dict):
            if field_name in row:
                return row[field_name]
            # Búsqueda insensible a mayúsculas
            for k in row.keys():
                if k.lower() == field_name.lower():
                    return row[k]
        
        # 2. Intentar acceso como atributo (común en pyodbc.Row)
        try:
            return getattr(row, field_name)
        except AttributeError:
            pass
            
        # 3. Intentar acceso por índice si el cursor lo permite
        if cursor.description:
            description = [d[0].lower() for d in cursor.description]
            if field_name.lower() in description:
                idx = description.index(field_name.lower())
                return row[idx]
    return None

def centrar(texto, ancho):
    """
    Centers text in a given width.
    """
    return texto.center(ancho)

def money(amount, decimals=2):
    """
    Formats currency.
    """
    try:
        return f"{float(amount):.2f}"
    except (ValueError, TypeError):
        return "0.00"
