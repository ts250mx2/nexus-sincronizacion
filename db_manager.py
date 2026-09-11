import pyodbc
import mysql.connector
import platform
import logging

# Driver incluido en Windows; en Linux usar 'ODBC Driver 18 for SQL Server'
DEFAULT_SQLSERVER_DRIVER = 'SQL Server'

class DatabaseManager:
    def __init__(self, config):
        self.config = config
        self.local_conn = None
        self.remote_conn = None
        self.arch = platform.architecture()[0]

    def connect_local(self):
        tipo = self.config['SETTINGS'].get('TipoLocal', 'sqlserver').lower()
        
        try:
            if tipo == 'sqlserver':
                c = self.config['LOCAL_SQLSERVER']
                driver = c.get('Driver', DEFAULT_SQLSERVER_DRIVER).strip('{}')
                conn_str = (
                    f"DRIVER={{{driver}}};"
                    f"SERVER={c['Servidor']};"
                    f"DATABASE={c['BaseDatos']};"
                    f"UID={c['Usuario']};"
                    f"PWD={c['Passwd']};"
                )
                # ODBC Driver 18 cifra por defecto y rechaza certificados autofirmados
                if c.getboolean('TrustServerCertificate', fallback=False):
                    conn_str += "TrustServerCertificate=yes;"
                self.local_conn = pyodbc.connect(conn_str)
                self.local_conn.execute("SET DATEFORMAT ymd")
                logging.info(f"Conectado a SQL Server Local con driver '{driver}' (DATEFORMAT ymd).")
            
            elif tipo == 'access':
                if self.arch == '32bit':
                    logging.warning("⚠️ NOTA: Estás usando Python de 32 bits. El script está optimizado para 64 bits.")
                
                c = self.config['LOCAL_ACCESS']
                path = c['RutaBD']
                # Common driver names for Access (64-bit engine uses these as well)
                drivers = [
                    '{Microsoft Access Driver (*.mdb, *.accdb)}',
                    '{Microsoft Access Driver (*.mdb)}',
                    'Microsoft Access Driver (*.mdb, *.accdb)'
                ]
                
                connected = False
                for drv in drivers:
                    try:
                        conn_str = f"DRIVER={drv};DBQ={path};"
                        self.local_conn = pyodbc.connect(conn_str)
                        logging.info(f"Conectado a Access Local usando {drv} (64-bit compatible).")
                        connected = True
                        break
                    except Exception:
                        continue
                
                if not connected:
                    raise Exception(f"No se pudo encontrar un driver de Access compatible para {path}")

            return True
        except Exception:
            logging.exception(f"Error conectando a Base de Datos Local ({tipo}):")
            return False

    def connect_remote(self):
        try:
            c = self.config['REMOTE_MYSQL']
            self.remote_conn = mysql.connector.connect(
                host=c['Servidor'],
                user=c['Usuario'],
                password=c['Passwd'],
                database=c['BaseDatos'],
                autocommit=True
            )
            logging.info("Conectado a MySQL Remoto.")
            return True
        except Exception:
            logging.exception("Error conectando a MySQL Remoto:")
            return False

    def close_all(self):
        if self.local_conn:
            self.local_conn.close()
        if self.remote_conn:
            self.remote_conn.close()
