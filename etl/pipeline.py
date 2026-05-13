"""Pipeline ETL: lee reportes SIGFE de data/raw/ y carga a SQLite.

Cada reporte SIGFE tiene su tabla destino. El pipeline:
1. Identifica el tipo de reporte por nombre de archivo
2. Lo carga con el loader apropiado
3. Normaliza columnas (renombra, parsea tipos)
4. Inserta en la tabla correspondiente con upsert por (folio, fecha_corte) cuando aplica

Uso:
    python -m etl.pipeline                          # ingesta todo desde data/raw
    python -m etl.pipeline --solo balance           # solo balance
    python -m etl.pipeline --raw data/raw/2026-04-30  # carpeta específica
"""
from pathlib import Path
import sqlite3
import argparse
import re
from datetime import datetime

import pandas as pd

from etl.loaders.sigfe import load_sigfe_report, load_sigfe_native_xlsx

# Mapeo: patrón en nombre de archivo → (tipo_reporte, tabla_destino, formato)
REPORT_MAP = [
    # (regex, tipo, tabla_sqlite, formato, [sheet_opcional])
    (r'SB_ListadoPagosRealizados',          'pagos',                       'pagos',                       'jasper'),
    (r'SB_ListadoCobrosRealizados',          'cobros',                      'cobros',                      'jasper'),
    (r'SB_BalanceComprobacionYSaldos',       'balance',                     'balance_snapshot',            'jasper'),
    (r'SB_MayorContable',                    'mayor_contable',              'mayor_contable',              'jasper'),
    (r'SB_DiarioContable',                   'diario_contable',             'diario_contable',             'jasper'),
    (r'SB_CarteraFinancieraBancaria',        'cartera_bancaria',            'cartera_bancaria_snapshot',   'jasper'),
    (r'SB_CarteraFinancieraContable',        'cartera_contable',            'cartera_contable_snapshot',   'jasper'),
    (r'SB_EstadoEjecucionPresupuestaria',    'estado_ejecucion',            'situacion_presupuestaria',    'jasper'),
    (r'SB_DescargaEstadosEjecucionPresupuestariaConceptos', 'desc_conceptos',  'ejecucion_concepto',       'jasper'),
    (r'SB_DescargaEstadosEjecucionPresupuestariaInsumos',   'desc_insumos',    'ejecucion_insumos',        'jasper'),
    (r'SB_ComparativoTransacciones',         'comp_transacciones',          'comparativo_transacciones',   'jasper'),
    (r'SB_ExportacionCuatroCatalogos',       'expo_catalogos',              'transacciones_ppto',          'jasper'),
    (r'SB_DisponibilidadDevengoPresupuestario', 'disp_devengo',             'disponibilidad_devengo',      'jasper'),
    (r'SB_ListadoDisponibilidadCompromiso',  'disp_compromiso',             'disponibilidad_compromiso',   'jasper'),
    (r'SB_ListadoDisponibilidadRequerimiento','disp_requerimiento',         'disponibilidad_requerimiento','jasper'),
    # Mayor Presupuestario: tablas separadas por etapa (Req/Comp/Dev) por esquema distinto
    # Detección por orden de los archivos descargados (sin un campo confiable en encabezado)
    # NOTA: si el usuario los descarga en otro orden, deberá renombrar agregando _req/_comp/_dev
    (r'SB_MayorPresupuestario(?:\.xls|__1_)', 'mayor_presup_req',          'mayor_presup_req',            'jasper'),
    (r'SB_MayorPresupuestario__(2|3)_',      'mayor_presup_comp',           'mayor_presup_comp',           'jasper'),
    (r'SB_MayorPresupuestario__(4|5)_',      'mayor_presup_dev',            'mayor_presup_dev',            'jasper'),
    (r'SB_EtapasCompromiso',                 'etapas_compromiso',           'etapas_compromiso',           'jasper'),
    (r'Tesorer.*_-_',                        'tesoreria',                   'tesoreria_snapshot',          'xlsx_nativo'),
    (r'Estado_de_Situación_Presupuestaria',  'estado_situacion',            'situacion_presupuestaria_oficial','xlsx_nativo'),
    (r'Estado_Compromiso_-_',                'estado_compromiso',           'estado_compromiso',           'xlsx_nativo'),
    (r'Pago_de_Facturas_Chile_Paga',         'chile_paga',                  'chile_paga_facturas',         'xlsx_nativo'),
    (r'Cartera_Financiera_Contable',         'cartera_contable_xlsx',       'cartera_contable_snapshot',   'xlsx_nativo'),
    (r'Cartera_Financiera_Presupuestaria_-_Compromiso', 'cartera_pres_comp',  'cartera_presup_compromiso', 'xlsx_nativo'),
    (r'Cartera_Financiera_Presupuestaria_-_Devengo',    'cartera_pres_dev',   'cartera_presup_devengo',    'xlsx_nativo'),
    (r'Diario_Presupuestario_-_Requerimiento','diario_pres_req',            'diario_presup_req',           'xlsx_nativo'),
    (r'Diario_Presupuestario_-_Compromiso',  'diario_pres_comp',            'diario_presup_comp',          'xlsx_nativo'),
    (r'Diario_Presupuestario_-_Devengo',     'diario_pres_dev',             'diario_presup_dev',           'xlsx_nativo'),
]


def detect_report_type(filename: str) -> tuple | None:
    """Devuelve (tipo, tabla, formato) o None si no se reconoce."""
    for pattern, tipo, tabla, formato in REPORT_MAP:
        if re.search(pattern, filename):
            return tipo, tabla, formato
    return None


def ingest_file(path: Path, conn: sqlite3.Connection, fecha_corte: str | None = None) -> dict:
    """Procesa un archivo y lo inserta en SQLite. Devuelve diccionario con info."""
    info = detect_report_type(path.name)
    if info is None:
        return {'archivo': path.name, 'status': 'desconocido', 'tabla': None}

    tipo, tabla, formato = info

    try:
        if formato == 'jasper':
            df, meta = load_sigfe_report(path)
        else:
            # xlsx nativo — la mayoría tienen datos en Sheet1
            # Cartera Financiera Contable xlsx web tiene resumen en Sheet1, detalle en Sheet2
            sheet_target = 'Sheet1'
            if 'Cartera_Financiera_Contable' in path.name:
                sheet_target = 'Sheet2'
            df, meta = load_sigfe_native_xlsx(path, sheet=sheet_target)

        if df.empty:
            return {'archivo': path.name, 'tipo': tipo, 'tabla': tabla, 'status': 'vacio', 'filas': 0}

        # Normalizar columnas (snake_case) + desambiguar duplicadas
        nuevas = []
        vistos = {}
        for c in df.columns:
            base = re.sub(r'\W+', '_', str(c).lower()).strip('_')
            if not base:
                base = 'col'
            if base in vistos:
                vistos[base] += 1
                nuevas.append(f"{base}_{vistos[base]}")
            else:
                vistos[base] = 1
                nuevas.append(base)
        df.columns = nuevas

        # Agregar metadata útil
        df['_archivo_origen'] = path.name
        df['_fecha_carga'] = datetime.now().isoformat(timespec='seconds')
        if fecha_corte:
            df['_fecha_corte'] = fecha_corte

        # Insertar (append; el manejo de duplicados se hace después con SQL)
        df.to_sql(tabla, conn, if_exists='append', index=False)
        conn.commit()

        return {
            'archivo': path.name, 'tipo': tipo, 'tabla': tabla,
            'status': 'ok', 'filas': len(df), 'cols': len(df.columns) - 3
        }

    except Exception as e:
        return {'archivo': path.name, 'tipo': tipo, 'tabla': tabla, 'status': f'error: {e}'}


def init_db(db_path: Path) -> sqlite3.Connection:
    """Inicializa SQLite y crea tablas de catálogo si no existen."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)

    # Tabla de cuentas bancarias (catálogo maestro)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS cuentas_bancarias (
        cuenta_id TEXT PRIMARY KEY,
        nro_cta_cte TEXT,
        nombre TEXT,
        programa TEXT,
        uso_permitido TEXT
    )""")
    # Pre-cargar las 17 cuentas SLEP si tabla está vacía
    if conn.execute("SELECT COUNT(*) FROM cuentas_bancarias").fetchone()[0] == 0:
        cuentas = [
            ('057', '21909000057', 'Subvención JUNJI',          'P02', 'Solo gastos jardines'),
            ('065', '21909000065', 'FAEP',                       'P02', 'Proyectos FAEP'),
            ('171', '21909000171', 'Asignación Familiar',        'P02', 'Reembolsos asig familiar'),
            ('260', '21909000260', 'RESTO P01',                  'P01', 'Gastos generales P01'),
            ('278', '21909000278', 'REMUNERACIÓN P01',           'P01', 'Personal P01'),
            ('324', '21909000324', 'Lic. Médicas FONASA',        'P02', 'Recuperaciones licencias'),
            ('332', '21909000332', 'Lic. Médicas ISAPRE',        'P02', 'Recuperaciones licencias'),
            ('341', '21909000341', 'Subvención General',         'P02', 'Subvención base'),
            ('359', '21909000359', 'PIE',                        'P02', 'Programa Integración Escolar'),
            ('367', '21909000367', 'SEP',                        'P02', 'Subvención Escolar Preferencial'),
            ('375', '21909000375', 'Subv. Mantenimiento',        'P02', 'Mantenimiento infraestructura'),
            ('383', '21909000383', 'Subv. Pro-Retención',        'P02', 'Pro-retención'),
            ('391', '21909000391', 'Remuneraciones P02',         'P02', 'Operativa pago remuneraciones'),
            ('405', '21909000405', 'Inversiones ST 31',          'P02', 'Iniciativas de inversión'),
            ('413', '21909000413', 'Aporte Fiscal Libre P02',    'P02', 'Aporte fiscal complementario'),
            ('421', '21909000421', 'Equipamiento Téc. Prof.',    'P02', 'Equipamiento técnico'),
            ('430', '21909000430', 'Liceos Bicentenarios',       'P02', 'Programa liceos bicentenarios'),
        ]
        conn.executemany(
            "INSERT INTO cuentas_bancarias VALUES (?,?,?,?,?)", cuentas
        )
        conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=Path, default=Path('data/raw'),
                        help='Carpeta con archivos SIGFE a ingestar')
    parser.add_argument('--db', type=Path, default=Path('data/slep.db'),
                        help='Ruta a SQLite')
    parser.add_argument('--solo', type=str, help='Filtrar por patrón (ej. balance)')
    parser.add_argument('--fecha-corte', type=str,
                        help='Fecha de corte de los reportes (YYYY-MM-DD)')
    args = parser.parse_args()

    conn = init_db(args.db)

    archivos = sorted([p for p in args.raw.rglob('*') if p.suffix in ('.xls', '.xlsx')])
    if args.solo:
        archivos = [p for p in archivos if args.solo.lower() in p.name.lower()]

    print(f"Procesando {len(archivos)} archivos desde {args.raw}\n")

    resultados = []
    for path in archivos:
        result = ingest_file(path, conn, fecha_corte=args.fecha_corte)
        resultados.append(result)
        status_icon = {'ok': '✅', 'vacio': '⚪', 'desconocido': '❓'}.get(
            result['status'], '❌')
        filas = result.get('filas', '-')
        tabla = result.get('tabla') or '?'
        print(f"{status_icon} {path.name[:60]:<60} → {tabla:<35} ({filas} filas)")

    # Resumen
    print(f"\n{'='*100}")
    df = pd.DataFrame(resultados)
    if not df.empty:
        print(f"Total: {len(df)} archivos")
        if 'status' in df.columns:
            print(df['status'].value_counts().to_string())

    conn.close()


if __name__ == '__main__':
    main()
