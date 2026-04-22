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
    
    try:
        # Cargar configuración
        config.read('config.ini')
        
        db_manager = DatabaseManager(config)
        engine = SyncEngine(db_manager, config)
        
        # Ejecutar Sincronización
        engine.execute_sync()
        
    except Exception:
        logging.exception("Error crítico durante la sincronización:")

if __name__ == "__main__":
    main()
