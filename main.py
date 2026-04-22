import logging
import configparser
from db_manager import DatabaseManager
from sync_engine import SyncEngine

import sys

# Configurar Logging
log_handlers = [logging.FileHandler('sync_nexus.log')]
if sys.stderr is not None:
    log_handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=log_handlers
)

import os

def main():
    config = configparser.ConfigParser()
    
    # Obtener la ruta absoluta del directorio del script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.ini')
    
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
