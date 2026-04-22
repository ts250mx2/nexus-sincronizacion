import logging
import sys
from datetime import datetime
from utils import valida_nulo, campo_requerido, centrar, money, format_sql_date
from tqdm import tqdm

class SyncEngine:
    def __init__(self, db_manager, config):
        self.db = db_manager
        self.config = config
        self.settings = config['SETTINGS']
        self.id_sucursal = self.settings.getint('IdSucursal')
        self.id_zona = self.settings.getint('IdZona')
        self.id_computadora = self.settings.getint('IdComputadora')

    def execute_sync(self):
        logging.info("Iniciando ciclo de sincronización...")
        
        if not self.db.connect_local() or not self.db.connect_remote():
            logging.error("No se pudo establecer conexión con ambas bases de datos.")
            return

        local_cur = None
        remote_cur = None
        try:
            local_cur = self.db.local_conn.cursor()
            # Si usamos pyodbc para el remoto en el futuro, esto podría fallar. 
            # Se asume mysql.connector por ahora.
            remote_cur = self.db.remote_conn.cursor(dictionary=True) 

            # 0. Validar IdSucursal (Prevención de mezcla de datos)
            self._execute(local_cur, "SELECT IdSucursal FROM tblValidaSucursal")
            row_val = local_cur.fetchone()
            if not row_val:
                raise Exception("No se encontró registro de validación en tblValidaSucursal")
            
            id_db = int(row_val[0]) if not isinstance(row_val, dict) else int(row_val['IdSucursal'])
            if id_db != self.id_sucursal:
                msg = f"\n{'!'*60}\n!!! ERROR CRÍTICO DE CONFIGURACIÓN !!!\nIdSucursal en config.ini ({self.id_sucursal}) NO COINCIDE con la Base de Datos ({id_db})\nSincronización abortada para prevenir mezcla de datos.\n{'!'*60}\n"
                if sys.stdout: print(msg)
                logging.error(f"Mismatch de Sucursal: Config={self.id_sucursal}, DB={id_db}")
                return

            # 1. Obtener fecha hoy del remoto
            sql = "SELECT NOW() AS FechaHoy"
            self._execute(remote_cur, sql)
            row = remote_cur.fetchone()
            if not row:
                raise Exception("No se pudo obtener la fecha del servidor remoto (SELECT NOW() no regresó resultados).")
            
            vl_fecha_hoy = row['FechaHoy'] if isinstance(row, dict) else row[0]
            vl_fecha_hoy_str = vl_fecha_hoy.strftime('%Y-%m-%d %H:%M:%S')

            # 2. Cargar fechas de sincronización
            vl_fecha_act = self.settings.get('FechaAct')
            
            #sql = f"SELECT DATE_SUB(FechaCorteInv, INTERVAL 2 DAY) AS FechaCorteInv FROM tblSucursales WHERE IdSucursal = {self.id_sucursal}"
            sql = f"SELECT FechaCorteInv FROM tblSucursales WHERE IdSucursal = {self.id_sucursal}"
            vl_fecha_act_inv = campo_requerido(remote_cur, sql, 'FechaCorteInv')
            vl_fecha_act_inv_str = format_sql_date(vl_fecha_act_inv)

            logging.info(f"Última transmisión: {vl_fecha_act_inv_str}")

            # 3. Sincronizar Movimientos (Tipo 99)
            self.sync_movements_99(local_cur, remote_cur, vl_fecha_act_inv_str)

            # 4. Sincronizar Artículos
            self.sync_articles(local_cur, remote_cur, vl_fecha_act)

            # 5. Artículos Bloqueados
            self.sync_blocked_articles(local_cur, remote_cur, vl_fecha_act)

            # 6. Socios
            self.sync_partners(local_cur, remote_cur, vl_fecha_act)

            # 7. Lista de Precios y Ticket
            self.sync_prices(local_cur, remote_cur, vl_fecha_act)

            # 8. Tablas Maestras (Lookup)
            self.sync_lookups(local_cur, remote_cur, vl_fecha_act)

            # 9. Reparar Traspasos (Lógica Remota)
            self.repair_transfers(remote_cur)

            # 10. Enviar Ventas
            self.push_sales(local_cur, remote_cur)

            # 11. Enviar Consignaciones
            self.push_consignments(local_cur, remote_cur)

            # 12. Enviar Configuracion Resurtido
            self.push_replenishment_config(local_cur, remote_cur)

            # 13. Enviar Devoluciones
            self.push_returns(local_cur, remote_cur)

            # 14. Enviar Aperturas, Retiros y Anticipos
            self.push_financial_records(local_cur, remote_cur)

            # 15. Sincronizar Movimientos Finales (No 99)
            self.sync_final_movements(local_cur, remote_cur)

            # Actualizar configuración local
            self.settings['FechaAct'] = vl_fecha_hoy_str
            self.settings['FechaActInv'] = vl_fecha_hoy_str
            self.settings['TodosProductos'] = '0'
            with open('config.ini', 'w') as configfile:
                self.config.write(configfile)

            logging.info("Sincronización finalizada exitosamente.")

        except Exception:
            logging.exception("Error durante la sincronización:")
        finally:
            if local_cur:
                local_cur.close()
            if remote_cur:
                remote_cur.close()
            self.db.close_all()

    def sync_movements_99(self, local_cur, remote_cur, fecha_inv):
        logging.info("Recibiendo Movimientos...")
        sql = f"DELETE FROM tblReporteMovimientos WHERE IdSucursal <> {self.id_sucursal}"
        self._execute(local_cur, sql)
        self.db.local_conn.commit()

        sql = f"SELECT * FROM tblReporteMovimientos WHERE TipoMovimiento = 99 AND IdSucursal = {self.id_sucursal} AND FechaAct > '{fecha_inv}' ORDER BY FechaAct"
        self._execute(remote_cur, sql)
        rows = remote_cur.fetchall()
        
        for row in tqdm(rows, desc="Movimientos", disable=sys.stdout is None):
            # local_cur.execute(f"DELETE FROM tblReporteMovimientos WHERE IdArticulo = {row['IdArticulo']} AND TipoMovimiento = 99")
            # En la lógica original hay dos deletes
            self._execute(local_cur, f"DELETE FROM tblReporteMovimientos WHERE IdArticulo = {row['IdArticulo']} AND TipoMovimiento = 99")
            self._execute(local_cur, f"DELETE FROM tblReporteMovimientos WHERE IdArticulo = {row['IdArticulo']} AND FechaAct <= '{format_sql_date(row['FechaAct'])}'")
            
            sql1 = "INSERT INTO tblReporteMovimientos(IdArticulo, IdSucursal, IdComputadora, TipoMovimiento, Folio, FechaMovimiento, Concepto, Mov, IdUsuario, EfectoInventario, Iteracion, FolioStr, FechaAct, EnLocal, Status) "
            sql2 = f"VALUES ({row['IdArticulo']},{row['IdSucursal']},{row['IdComputadora']},{row['TipoMovimiento']},{row['Folio']},{valida_nulo(row['FechaMovimiento'], True)},{valida_nulo(row['Concepto'], True)},{row['Mov']},{row['IdUsuario']},{row['EfectoInventario']},{row['Iteracion']},{valida_nulo(row.get('FolioStr'), True)},'{format_sql_date(row['FechaAct'])}',{row['EnLocal']},{row['Status']})"
            self._execute(local_cur, sql1 + sql2)
            
            # Marcar como transmitido en remoto
            self._execute(remote_cur, f"UPDATE tblReporteProcesosInventariosDif{self.id_sucursal} SET Transmitir = 0 WHERE IdArticulo = {row['IdArticulo']} AND TipoMovimiento = 99")
            self.db.local_conn.commit()

    def sync_articles(self, local_cur, remote_cur, fecha_act):
        logging.info("Recibiendo Artículos...")
        vl_todos = self.settings.getint('TodosProductos', 0)
        if vl_todos == 1:
            sql = "SELECT * FROM tblArticulos ORDER BY IdArticulo"
        else:
            sql = f"SELECT * FROM tblArticulos WHERE FechaAct >= '{fecha_act}' ORDER BY IdArticulo"
        
        self._execute(remote_cur, sql)
        rows = remote_cur.fetchall()
        
        for row in tqdm(rows, desc="Artículos", disable=sys.stdout is None):
            self._execute(local_cur, f"DELETE FROM tblArticulos WHERE IdArticulo = {row['IdArticulo']}")
            
            fields = "IdArticulo, Codigo, Descripcion, Producto, Marca, Color, Talla, Status, EsGuia, IdTipoProducto, CodigoBarras, Puntos, AceptaPuntos, CantidadCombo, ProductosOpcionales, Depto, Modelo, Clasificacion, PrecioBase, AplicaPrecio1, AplicaPrecio2, AplicaPrecio3, AplicaPrecio4"
            values = f"{row['IdArticulo']},'{row['Codigo']}','{row['Descripcion']}','{row['Producto']}','{row['Marca']}','{row['Color']}','{row['Talla']}',{row['Status']},{valida_nulo(row.get('EsGuia'))},{valida_nulo(row.get('IdTipoProducto'))},{valida_nulo(row.get('CodigoBarras'), True)},{valida_nulo(row.get('Puntos'))},{valida_nulo(row.get('AceptaPuntos'))},{valida_nulo(row.get('CantidadCombo'))},{valida_nulo(row.get('ProductosOpcionales'))},{valida_nulo(row.get('Depto'), True)},{valida_nulo(row.get('Modelo'), True)},{valida_nulo(row.get('Clasificacion'), True)},{valida_nulo(row.get('PrecioBase'))},{valida_nulo(row.get('AplicaPrecio1'))},{valida_nulo(row.get('AplicaPrecio2'))},{valida_nulo(row.get('AplicaPrecio3'))},{valida_nulo(row.get('AplicaPrecio4'))}"
            self._execute(local_cur, f"INSERT INTO tblArticulos({fields}) VALUES({values})")
            
            # Inventario inicial si no existe
            self._execute(local_cur, f"SELECT IdArticulo FROM tblArticulosInventarios WHERE IdArticulo = {row['IdArticulo']}")
            if not local_cur.fetchone() and row['IdArticulo'] > 0:
                self._execute(local_cur, f"INSERT INTO tblArticulosInventarios(IdArticulo, IdSucursal, ExiInicial, Entradas, Salidas, ExiFinal, FechaAct) VALUES({row['IdArticulo']},{self.id_sucursal}, 0, 0, 0, 0, GETDATE())")
            
            # Paquetes
            self._execute(local_cur, f"DELETE FROM tblDetallePaquetes WHERE IdArticulo = {row['IdArticulo']}")
            self._execute(remote_cur, f"SELECT * FROM tblDetallePaquetes WHERE IdArticulo = {row['IdArticulo']} ORDER BY IdArticulo")
            paquetes = remote_cur.fetchall()
            for p in paquetes:
                self._execute(local_cur, f"INSERT INTO tblDetallePaquetes(IdArticulo, IdArticuloHijo, Cantidad, Descuento) VALUES({p['IdArticulo']},{p['IdArticuloHijo']},{p['Cantidad']},{p['Descuento']})")
        
        self.db.local_conn.commit()

    def sync_blocked_articles(self, local_cur, remote_cur, fecha_act):
        logging.info("Bloqueando Artículos...")
        sql = f"SELECT * FROM tblArticulosBloqueados WHERE FechaBloqueo >= '{fecha_act}' AND IdSucursal = {self.id_sucursal} ORDER BY IdArticulo"
        self._execute(remote_cur, sql)
        for row in remote_cur.fetchall():
            local_cur.execute(f"UPDATE tblArticulos SET Status = 1 WHERE IdArticulo = {row['IdArticulo']}")
        self.db.local_conn.commit()

    def sync_partners(self, local_cur, remote_cur, fecha_act):
        logging.info("Recibiendo Socios...")
        sql = f"SELECT * FROM tblSocios WHERE FechaAct >= '{fecha_act}' ORDER BY IdSocio"
        self._execute(remote_cur, sql)
        rows = remote_cur.fetchall()
        for row in rows:
            self._execute(local_cur, f"DELETE FROM tblSocios WHERE IdSocio = {row['IdSocio']}")
            fields = "IdSocio, Socio, RFC, Direccion, Municipio, Colonia, Pais, Telefonos, CorreoElectronico, Contacto, EsProveedor, EsDistribuidor, EsMayoreo, Status, EsCredito, EsForaneo, Credito, LimiteCredito, LimiteCreditoDias, CreditoInicial"
            vals = f"{row['IdSocio']},{valida_nulo(row['Socio'],True)},{valida_nulo(row['RFC'],True)},{valida_nulo(row['Direccion'],True)},{valida_nulo(row['Municipio'],True)},{valida_nulo(row['Colonia'],True)},{valida_nulo(row['Pais'],True)},{valida_nulo(row['Telefonos'],True)},{valida_nulo(row['CorreoElectronico'],True)},{valida_nulo(row['Contacto'],True)},{valida_nulo(row['EsProveedor'])},{valida_nulo(row['EsDistribuidor'])},{valida_nulo(row['EsMayoreo'])},{valida_nulo(row['Status'])},{valida_nulo(row['EsCredito'])},{valida_nulo(row['EsForaneo'])},{valida_nulo(row['Credito'])},{valida_nulo(row['LimiteCredito'])},{valida_nulo(row['LimiteCreditoDias'])},{valida_nulo(row['CreditoInicial'])}"
            self._execute(local_cur, f"INSERT INTO tblSocios({fields}) VALUES({vals})")
        self.db.local_conn.commit()

    def sync_prices(self, local_cur, remote_cur, fecha_act):
        logging.info("Actualizando Precios...")
        vl_todos = self.settings.getint('TodosProductos', 0)
        if vl_todos == 1:
            sql = f"SELECT A.*, Descripcion, Codigo FROM tblListaPrecios A INNER JOIN tblArticulos B ON A.IdArticulo = B.IdArticulo WHERE IdZona = {self.id_zona} ORDER BY IdArticulo"
        else:
            sql = f"SELECT A.*, Descripcion, Codigo FROM tblListaPrecios A INNER JOIN tblArticulos B ON A.IdArticulo = B.IdArticulo WHERE IdZona = {self.id_zona} AND A.FechaAct >= '{fecha_act}' ORDER BY IdArticulo"
        
        self._execute(remote_cur, sql)
        rows = remote_cur.fetchall()
        if not rows: return

        puerto = self.settings.get('PuertoTicket', 'ticket.txt')
        with open(puerto, 'a') as f:
            f.write(f"\n{centrar('**** CAMBIOS DE PRECIO ****', 40)}\n")
            f.write("========================================\n")
            
            for row in rows:
                # Update remote tracking
                sql_rep = "REPLACE INTO tblArticulosSucursalesActualizaciones(IdArticulo, IdSucursal, Precio1, Precio2, Precio3, Precio4, FechaAct, Bloqueo) "
                sql_vals = f"VALUES({row['IdArticulo']},{self.id_sucursal},{row['Precio1']},{row['Precio2']},{row['Precio3']},{row['Precio4']}, NOW(), 0)"
                self._execute(remote_cur, sql_rep + sql_vals)
                
                # Ticket entry
                f.write(f"{row['Codigo']:10} {row['Descripcion'][:28]}\n")
                f.write(f"PP {money(row['Precio1']):10} PM {money(row['Precio2']):10} PD {money(row['Precio3']):10}\n")
                
                # Local update
                self._execute(local_cur, f"UPDATE tblArticulos SET ConPrecio = 1, Precio1 = {row['Precio1']}, Precio2 = {row['Precio2']}, Precio3 = {row['Precio3']}, Precio4 = {row['Precio4']} WHERE IdArticulo = {row['IdArticulo']}")
            
            f.write("========================================\n")
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        self.db.local_conn.commit()

    def sync_lookups(self, local_cur, remote_cur, fecha_act):
        tables = ['tblCategorias', 'tblUsuarios', 'tblSucursales', 'tblZonas', 'tblTiposPago', 'tblBancos']
        for table in tables:
            logging.info(f"Recibiendo {table}...")
            self._execute(remote_cur, f"SELECT * FROM {table} WHERE FechaAct >= '{fecha_act}'")
            rows = remote_cur.fetchall()
            id_col = table.replace('tbl', 'Id')[:-1] if not table.endswith('es') else table.replace('tbl', 'Id')[:-2]
            # Custom ID column logic if naming isn't standard
            if table == 'tblSucursales': id_col = 'IdSucursal'
            elif table == 'tblZonas': id_col = 'IdZona'
            elif table == 'tblTiposPago': id_col = 'IdTipoPago'
            elif table == 'tblCategorias': id_col = 'IdCategoria'
            elif table == 'tblUsuarios': id_col = 'IdUsuario'
            elif table == 'tblBancos': id_col = 'IdBanco'

            for row in rows:
                self._execute(local_cur, f"DELETE FROM {table} WHERE {id_col} = {row[id_col]}")
                cols = ", ".join(row.keys())
                placeholders = ", ".join([valida_nulo(v, isinstance(v, str)) for v in row.values()])
                self._execute(local_cur, f"INSERT INTO {table}({cols}) VALUES({placeholders})")
        self.db.local_conn.commit()

    def repair_transfers(self, remote_cur):
        logging.info("Reparando Traspasos...")
        sql = "SELECT A.IdTraspaso, B.IdOrdenCompra, B.Iteracion FROM tblTraspasos A INNER JOIN tblOrdenesCompra B ON A.IdTraspaso = B.IdTraspaso WHERE A.IdTraspaso NOT IN (SELECT IdTraspaso FROM tblDetalleTraspasos) AND A.FechaAct > DATE_SUB(NOW(), INTERVAL 1 DAY) AND A.Reparado = 0"
        self._execute(remote_cur, sql)
        for row in remote_cur.fetchall():
            # (Simplificando lógica de reparación para brevedad, replicando VB6)
            sql_max = f"SELECT MAX(Iteracion) AS MaxIteracion FROM tblOrdenesCompra WHERE IdOrdenCompra = {row['IdOrdenCompra']}"
            self._execute(remote_cur, sql_max)
            max_iter = remote_cur.fetchone()['MaxIteracion']
            
            if max_iter == row['Iteracion']:
                sql_ins = f"REPLACE INTO tblDetalleTraspasos(IdTraspaso, IdArticulo, Cantidad, Costo, IdRenglon, Caja) " \
                          f"SELECT {row['IdTraspaso']}, A.IdArticulo, A.Cantidad, A.Costo, 1, 1 FROM tblDetalleOrdenesCompra A " \
                          f"WHERE A.IdOrdenCompra = {row['IdOrdenCompra']} AND A.Iteracion = {row['Iteracion']}"
                self._execute(remote_cur, sql_ins)
            
            self._execute(remote_cur, f"UPDATE tblTraspasos SET FechaAct = NOW(), Reparado = 1 WHERE IdTraspaso = {row['IdTraspaso']}")

    def push_sales(self, local_cur, remote_cur):
        logging.info("Enviando Ventas...")
        # Lógica de tblVentasFast
        self._execute(local_cur, "INSERT INTO tblVentasFast SELECT * FROM tblVentas WHERE FechaVenta > GETDATE()-7 AND IdVenta NOT IN (SELECT IdVenta FROM tblVentasFast)")
        self.db.local_conn.commit()

        self._execute(local_cur, f"SELECT * FROM tblVentasFast WHERE Transmitido = 0 AND IdSucursal = {self.id_sucursal} ORDER BY IdVenta")
        for row in local_cur.fetchall():
            logging.info(f"Enviando Venta {row.FolioVenta}")
            self._execute(remote_cur, f"DELETE FROM tblDetalleVentas WHERE IdVenta = {row.IdVenta} AND IdSucursal = {self.id_sucursal}")
            
            # Insert Venta (mapping common fields)
            cols = "IdVenta, IdComputadora, EsTarjeta, IdVentaFolio, FolioVenta, FechaVenta, IdUsuarioVenta, Total, IdSucursal, Status, Impresiones, IdSocio, Cuenta, TipoVenta, Cliente, CorreoElectronico, RFC, Telefonos, Contacto, IdCotizacion, Pago, Descuentos, IdApertura, IdTipoPago, IdBanco, Guia, Prorrateo, Credito, Anticipo, IdAnticipo, Adeudo, Parcialidad, TotalPago, IdSupervisorCredito, PagoAdeudo, IdTipoPago2, Pago2, IdBanco2, Cuenta2, IdTipoPago3, Pago3, IdBanco3, Cuenta3, FechaAct"
            values = f"{row.IdVenta},{row.IdComputadora},{row.EsTarjeta},{row.IdVentaFolio},'{row.FolioVenta}','{format_sql_date(row.FechaVenta)}',{row.IdUsuarioVenta},{row.Total},{self.id_sucursal},{row.Status},{row.Impresiones},{valida_nulo(row.IdSocio)},{valida_nulo(row.Cuenta,True)},{valida_nulo(row.TipoVenta)},{valida_nulo(row.Cliente,True)},{valida_nulo(row.CorreoElectronico,True)},{valida_nulo(row.RFC,True)},{valida_nulo(row.Telefonos,True)},{valida_nulo(row.Contacto,True)},{valida_nulo(row.IdCotizacion)},{valida_nulo(row.Pago)},{valida_nulo(row.Descuentos)},{valida_nulo(row.IdApertura)},{valida_nulo(row.IdTipoPago)},{valida_nulo(row.IdBanco)},{valida_nulo(row.Guia,True)},{valida_nulo(row.Prorrateo)},{valida_nulo(row.Credito)},{valida_nulo(row.Anticipo)},{valida_nulo(row.IdAnticipo)},{valida_nulo(row.Adeudo)},{valida_nulo(row.Parcialidad)},{valida_nulo(row.TotalPago)},{valida_nulo(row.IdSupervisorCredito)},{valida_nulo(row.PagoAdeudo)},{valida_nulo(row.IdTipoPago2)},{valida_nulo(row.Pago2)},{valida_nulo(row.IdBanco2)},{valida_nulo(row.Cuenta2,True)},{valida_nulo(row.IdTipoPago3)},{valida_nulo(row.Pago3)},{valida_nulo(row.IdBanco3)},{valida_nulo(row.Cuenta3,True)}, NOW()"
            self._execute(remote_cur, f"REPLACE INTO tblVentas({cols}) VALUES({values})")
            
            # Detalle Ventas
            self._execute(local_cur, f"SELECT * FROM tblDetalleVentas WHERE IdVenta = {row.IdVenta} AND IdSucursal = {self.id_sucursal}")
            for d in local_cur.fetchall():
                self._execute(remote_cur, f"INSERT INTO tblDetalleVentas(IdVenta, IdSucursal, IdArticulo, Cantidad, PrecioVenta, Descuento, Iva, IdRenglon, IdTipoPrecio, Precio, DescripcionVenta, IdVentaCredito, IdSucursalVentaCredito, Defecto) VALUES({d.IdVenta},{d.IdSucursal},{d.IdArticulo},{d.Cantidad},{d.PrecioVenta},{d.Descuento},{d.Iva},{d.IdRenglon},{d.IdTipoPrecio},{d.Precio},{valida_nulo(d.DescripcionVenta,True)},{valida_nulo(d.IdVentaCredito)},{valida_nulo(d.IdSucursalVentaCredito)},{valida_nulo(d.Defecto)})")
            
            self._execute(local_cur, f"UPDATE tblVentas SET Transmitido = 1 WHERE IdVenta = {row.IdVenta} AND IdSucursal = {self.id_sucursal}")
            self._execute(local_cur, f"UPDATE tblVentasFast SET Transmitido = 1 WHERE IdVenta = {row.IdVenta} AND IdSucursal = {self.id_sucursal}")
        self.db.local_conn.commit()

    def push_consignments(self, local_cur, remote_cur):
        logging.info("Enviando Consignaciones...")
        self._execute(local_cur, f"SELECT * FROM tblConsignaciones WHERE Transmitido = 0 AND IdSucursal = {self.id_sucursal} ORDER BY IdConsignacion")
        for row in local_cur.fetchall():
            self._execute(remote_cur, f"DELETE FROM tblDetalleConsignaciones WHERE IdConsignacion = {row.IdConsignacion} AND IdSucursal = {self.id_sucursal}")
            cols = "IdConsignacion, IdSucursal, FechaConsignacion, IdSocio, Status, Cerrada, IdVenta, IdUsuarioConsignacion, Evento, CantProductos, Total, FechaAct, EnLocal, Reinventario"
            vals = f"{row.IdConsignacion},{row.IdSucursal},'{format_sql_date(row.FechaConsignacion)}',{row.IdSocio},{row.Status},{row.Cerrada},{row.IdVenta},{row.IdUsuarioConsignacion},'{row.Evento}',{row.CantProductos},{row.Total}, NOW(), {valida_nulo(row.EnLocal)}, {valida_nulo(row.Reinventario)}"
            self._execute(remote_cur, f"REPLACE INTO tblConsignaciones({cols}) VALUES({vals})")
            
            self._execute(local_cur, f"SELECT * FROM tblDetalleConsignaciones WHERE IdConsignacion = {row.IdConsignacion}")
            for d in local_cur.fetchall():
                self._execute(remote_cur, f"INSERT INTO tblDetalleConsignaciones(IdConsignacion, IdArticulo, Precio, CantidadSalida, IdRenglon, CantidadEntrada, IdSucursal) VALUES({d.IdConsignacion},{d.IdArticulo},{d.Precio},{d.CantidadSalida},{d.IdRenglon},{d.CantidadEntrada},{self.id_sucursal})")
            
            self._execute(local_cur, f"UPDATE tblConsignaciones SET Transmitido = 1 WHERE IdConsignacion = {row.IdConsignacion} AND IdSucursal = {self.id_sucursal}")
        self.db.local_conn.commit()

    def push_replenishment_config(self, local_cur, remote_cur):
        logging.info("Enviando Configuración de Resurtido...")
        sql = "SELECT * FROM vlBufferConfiguracionResurtido WHERE DiasSurtido <> DiasSurtidoAnt OR DiasMin <> DiasMinAnt OR DiasMax <> DiasMaxAnt OR PVM15 <> PVM15Ant OR ExiMinRes <> ExiMinResAnt "
        self._execute(local_cur, sql)
        for row in local_cur.fetchall():
            self._execute(remote_cur, f"REPLACE INTO tblConfiguracionResurtido(IdArticulo, IdSucursal, DiasMin, DiasMax, DiasSurtido, PVM15, ExiMinRes) VALUES({row.IdArticulo}, {self.id_sucursal}, {valida_nulo(row.DiasMin)}, {valida_nulo(row.DiasMax)}, {valida_nulo(row.DiasSurtido)}, {valida_nulo(row.PVM15)}, {valida_nulo(row.ExiMinRes)})")
            self._execute(local_cur, f"UPDATE tblBufferConfiguracionResurtido SET DiasSurtidoAnt = DiasSurtido, DiasMinAnt = DiasMin, DiasMaxAnt = DiasMax, PVM15Ant = PVM15, ExiMinResAnt = ExiMinRes WHERE IdArticulo = {row.IdArticulo}")
        self.db.local_conn.commit()

    def push_returns(self, local_cur, remote_cur):
        logging.info("Enviando Devoluciones...")
        self._execute(local_cur, "SELECT * FROM tblDevoluciones WHERE Transmitido = 0 ORDER BY IdDevolucion")
        for row in local_cur.fetchall():
            self._execute(remote_cur, f"DELETE FROM tblDetalleDevoluciones WHERE IdDevolucion = {row.IdDevolucion} AND IdSucursal = {self.id_sucursal}")
            cols = "IdDevolucion, IdSucursal, FechaDevolucion, CantProductos, Total, Status, Saldo, ConDefecto, IdVenta, IdSucursalVenta, IdUsuarioDevolucion"
            vals = f"{row.IdDevolucion},{row.IdSucursal},'{format_sql_date(row.FechaDevolucion)}',{row.CantProductos},{row.Total},{row.Status},{row.Saldo},{row.ConDefecto},{row.IdVenta},{row.IdSucursalVenta},{row.IdUsuarioDevolucion}"
            self._execute(remote_cur, f"REPLACE INTO tblDevoluciones({cols}) VALUES({vals})")
            
            self._execute(local_cur, f"SELECT * FROM tblDetalleDevoluciones WHERE IdDevolucion = {row.IdDevolucion} AND IdSucursal = {self.id_sucursal}")
            for d in local_cur.fetchall():
                self._execute(remote_cur, f"INSERT INTO tblDetalleDevoluciones(IdDevolucion, IdSucursal, IdArticulo, Cantidad, PrecioVenta, IdRenglon, Dev) VALUES({d.IdDevolucion},{d.IdSucursal},{d.IdArticulo},{d.Cantidad},{d.PrecioVenta},{d.IdRenglon},{d.Dev})")
            
            self._execute(local_cur, f"UPDATE tblDevoluciones SET Transmitido = 1 WHERE IdDevolucion = {row.IdDevolucion} AND IdSucursal = {self.id_sucursal}")
        self.db.local_conn.commit()

    def push_financial_records(self, local_cur, remote_cur):
        # Aperturas
        logging.info("Enviando Aperturas...")
        self._execute(local_cur, "SELECT * FROM tblAperturasCierres WHERE Transmitido = 0 ORDER BY IdApertura")
        for row in local_cur.fetchall():
            fecha_cierre = format_sql_date(row.FechaCierre) if row.FechaCierre else "2000-01-01"
            cols = "IdApertura, IdSucursal, FechaApertura, IdSupervisor, FondoCaja, FechaCierre, Efectivo, IdSupervisorCierre, Impresiones, TotalVentas"
            vals = f"{row.IdApertura},{self.id_sucursal},'{format_sql_date(row.FechaApertura)}',{row.IdSupervisor},{row.FondoCaja},'{fecha_cierre}',{row.Efectivo},{row.IdSupervisorCierre},{row.Impresiones},{row.TotalVentas}"
            self._execute(remote_cur, f"REPLACE INTO tblAperturasCierres({cols}) VALUES({vals})")
            self._execute(local_cur, f"UPDATE tblAperturasCierres SET Transmitido = 1 WHERE IdApertura = {row.IdApertura}")
        
        # Retiros
        logging.info("Enviando Retiros...")
        self._execute(local_cur, "SELECT * FROM tblRetiros WHERE Transmitido = 0 ORDER BY IdRetiro")
        for row in local_cur.fetchall():
            cols = "IdRetiro, IdSucursal, IdUsuario, FechaRetiro, Efectivo, Status, TipoRetiro, IdApertura, IdComputadora"
            vals = f"{row.IdRetiro},{self.id_sucursal},{row.IdUsuario},'{format_sql_date(row.FechaRetiro)}',{row.Efectivo},{row.Status},{row.TipoRetiro},{row.IdApertura},{row.IdComputadora}"
            self._execute(remote_cur, f"REPLACE INTO tblRetiros({cols}) VALUES({vals})")
            self._execute(local_cur, f"UPDATE tblRetiros SET Transmitido = 1 WHERE IdRetiro = {row.IdRetiro}")
        
        # Anticipos
        logging.info("Enviando Anticipos...")
        self._execute(local_cur, "SELECT * FROM tblAnticipos WHERE Transmitido = 0 ORDER BY IdAnticipo")
        for row in local_cur.fetchall():
            self._execute(remote_cur, f"REPLACE INTO tblAnticipos(IdAnticipo, IdSocio, Anticipo, IdVenta, IdSucursal, Gasto, IdDevolucion) VALUES({row.IdAnticipo},{row.IdSocio},{row.Anticipo},{row.IdVenta},{self.id_sucursal},{row.Gasto},{row.IdDevolucion})")
            self._execute(local_cur, f"UPDATE tblAnticipos SET Transmitido = 1 WHERE IdAnticipo = {row.IdAnticipo}")
        
        self.db.local_conn.commit()

    def sync_final_movements(self, local_cur, remote_cur):
        logging.info("Recibiendo Movimientos Finales...")
        sql = f"SELECT FechaCorteInv FROM tblSucursales WHERE IdSucursal = {self.id_sucursal}"
        fecha_corte = campo_requerido(remote_cur, sql, 'FechaCorteInv')
        fecha_corte_str = format_sql_date(fecha_corte) or "2000-01-01"

        self._execute(local_cur, f"DELETE FROM tblReporteMovimientos WHERE FechaMovimiento < '{fecha_corte_str}' AND TipoMovimiento <> 99")
        
        sql = f"SELECT * FROM tblReporteMovimientos WHERE Status = 0 AND TipoMovimiento NOT IN (1,99) AND IdSucursal = {self.id_sucursal} AND FechaMovimiento > '{fecha_corte_str}' ORDER BY FechaAct"
        self._execute(remote_cur, sql)
        for row in remote_cur.fetchall():
            self._execute(local_cur, f"DELETE FROM tblReporteMovimientos WHERE IdArticulo = {row['IdArticulo']} AND TipoMovimiento = {row['TipoMovimiento']} AND Iteracion = {row['Iteracion']} AND Folio = {row['Folio']}")
            sql1 = "INSERT INTO tblReporteMovimientos(IdArticulo, IdSucursal, IdComputadora, TipoMovimiento, Folio, FechaMovimiento, Concepto, Mov, IdUsuario, EfectoInventario, Iteracion, FolioStr, FechaAct, EnLocal, Status) "
            sql2 = f"VALUES ({row['IdArticulo']},{row['IdSucursal']},{row['IdComputadora']},{row['TipoMovimiento']},{row['Folio']},'{format_sql_date(row['FechaMovimiento'])}',{valida_nulo(row['Concepto'],True)},{row['Mov']},{row['IdUsuario']},{row['EfectoInventario']},{row['Iteracion']},'{row['FolioStr']}','{format_sql_date(row['FechaAct'])}',{row['EnLocal']},{row['Status']})"
            self._execute(local_cur, sql1 + sql2)
        
        # Registro de transmision final en remoto
        self._execute(remote_cur, f"REPLACE INTO tblSucursalesTransmisiones(IdSucursal, IdComputadora, Computadora, Version, FechaTransmision) VALUES({self.id_sucursal},{self.id_computadora},'{self.settings['Computadora']}','{self.settings['Version']}', NOW())")
        self.db.local_conn.commit()

    def _execute(self, cursor, sql, params=None):
        """
        Ejecuta una consulta SQL y registra el contenido exacto en caso de error.
        """
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
        except Exception as e:
            logging.error("!" * 80)
            logging.error("ERROR DE EJECUCIÓN SQL")
            logging.error(f"Consulta: {sql}")
            if params:
                logging.error(f"Parámetros: {params}")
            logging.error(f"Error: {e}")
            logging.error("!" * 80)
            # También imprimir en consola para visibilidad inmediata si el usuario está observando
            if sys.stdout: print(f"\n{'!'*20} ERROR SQL {'!'*20}\n{sql}\nError: {e}\n{'!'*51}")
            raise
