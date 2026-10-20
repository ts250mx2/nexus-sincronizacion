import logging
import configparser
from db_manager import DatabaseManager
from sync_engine import SyncEngine
from utils import CONFIG_PATH, ruta_del_proyecto

import os
import sys

log_file = ruta_del_proyecto('sync_nexus.log')

# Configurar Logging
log_handlers = [logging.FileHandler(log_file)]
if sys.stderr is not None:
    log_handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=log_handlers
)

def main():
    config = configparser.ConfigParser()
    
    config_path = CONFIG_PATH
    
    try:
        # Cargar configuración
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"No se encontró el archivo de configuración en: {config_path}")
            
        config.read(config_path)
        
        if not config.has_section('SETTINGS'):
            raise KeyError("No se encontró la sección [SETTINGS] en config.ini")
        
        db_manager = DatabaseManager(config)
        engine = SyncEngine(db_manager, config)
        
        # Ejecutar Sincronización
        engine.execute_sync()
        
    except Exception as e:
        logging.exception("Error crítico durante la sincronización:")
        if sys.stdout:
            print(f"\n[ ERROR ] {e}")

if __name__ == "__main__":
    main()
