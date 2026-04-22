import time
import logging
import configparser
from db_manager import DatabaseManager
from sync_engine import SyncEngine

# Configurar Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('sync_nexus.log')
    ]
)

def main():
    config = configparser.ConfigParser()
    
    while True:
        try:
            # Recargar configuración en cada ciclo para permitir cambios en caliente
            config.read('config.ini')
            
            db_manager = DatabaseManager(config)
            engine = SyncEngine(db_manager, config)
            
            # Ejecutar Sincronización
            engine.execute_sync()
            
            interval = config['SETTINGS'].getint('SyncIntervalMinutes', 5)
            logging.info(f"Esperando {interval} minutos para el siguiente ciclo...")
            time.sleep(interval * 60)
            
        except KeyboardInterrupt:
            logging.info("Sincronización detenida por el usuario.")
            break
        except Exception:
            logging.exception("Error crítico en el bucle principal:")
            logging.info("Reintentando en 60 segundos...")
            time.sleep(60)

if __name__ == "__main__":
    main()
