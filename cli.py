"""
CLI SLEP Petorca — Sistema de Gestión Financiera

Uso:
    python cli.py update    [--raw PATH] [--fecha-corte YYYY-MM-DD]
    python cli.py status
    python cli.py conciliar
    python cli.py disponible
    python cli.py flujo
    python cli.py dashboard [--output PATH]
    python cli.py saldo --cuenta ID --monto MONTO [--fecha YYYY-MM-DD]
    python cli.py saldo-lote --archivo PATH [--fecha YYYY-MM-DD]
"""
import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

DB_DEFAULT = Path("data/slep.db")


def cmd_update(args):
    """Ingesta reportes SIGFE desde data/raw/ a SQLite."""
    from etl.pipeline import main as pipeline_main
    sys.argv = ["pipeline"]
    if args.raw:
        sys.argv += ["--raw", args.raw]
    if args.fecha_corte:
        sys.argv += ["--fecha-corte", args.fecha_corte]
    if args.db:
        sys.argv += ["--db", args.db]
    pipeline_main()


def cmd_status(args):
    """KPIs de salud financiera: caja, deuda flotante, alertas."""
    from analytics.salud_financiera import imprimir
    imprimir(Path(args.db))


def cmd_conciliar(args):
    """Conciliación SIGFE 11102 ↔ saldos BancoEstado."""
    from analytics.conciliacion import conciliar, imprimir
    resultado = conciliar(Path(args.db))
    imprimir(resultado)


def cmd_disponible(args):
    """Disponibilidad presupuestaria por programa y subtítulo."""
    from analytics.disponible_ff import imprimir
    imprimir(Path(args.db))


def cmd_flujo(args):
    """Flujo de caja histórico y proyección mensual."""
    from analytics.flujo_caja import imprimir
    imprimir(Path(args.db))


def cmd_dashboard(args):
    """Genera el dashboard HTML en reports/output/dashboard.html."""
    import subprocess, sys as _sys
    from reports.dashboard import generar
    out = Path(args.output) if args.output else None
    kwargs = {"db_path": Path(args.db)}
    if out:
        kwargs["output"] = out
    ruta = generar(**kwargs)
    # Intentar abrir en el navegador
    try:
        import webbrowser
        webbrowser.open(ruta.as_uri())
    except Exception:
        pass


def cmd_saldo(args):
    """
    Registra saldo bancario diario de una cuenta.

    Ejemplo:
        python cli.py saldo --cuenta 341 --monto 125000000
        python cli.py saldo --cuenta 391 --monto 87500000 --fecha 2026-05-12
    """
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saldos_bancarios_diarios (
            fecha      TEXT NOT NULL,
            cuenta_id  TEXT NOT NULL,
            saldo      REAL NOT NULL,
            PRIMARY KEY (fecha, cuenta_id)
        )
    """)

    fecha = args.fecha or date.today().isoformat()

    # Validar que la cuenta exista en el catálogo
    row = conn.execute(
        "SELECT nombre, programa FROM cuentas_bancarias WHERE cuenta_id = ?",
        (args.cuenta,)
    ).fetchone()

    if not row:
        print(f"⚠️  Cuenta '{args.cuenta}' no encontrada en catálogo.")
        print("    Cuentas válidas: 057 065 171 260 278 324 332 341 359 367 375 383 391 405 413 421 430")
        conn.close()
        sys.exit(1)

    nombre, programa = row
    conn.execute(
        "INSERT OR REPLACE INTO saldos_bancarios_diarios (fecha, cuenta_id, saldo) VALUES (?, ?, ?)",
        (fecha, args.cuenta, args.monto)
    )
    conn.commit()
    conn.close()

    print(f"✅ Saldo registrado: [{fecha}] {nombre} ({programa}) — ${args.monto:,.0f}")


def cmd_saldo_lote(args):
    """
    Registra saldos de múltiples cuentas desde un CSV simple.

    Formato CSV (sin cabecera): cuenta_id,monto
    Ejemplo:
        341,125000000
        391,87500000
        260,15000000
    """
    db_path = Path(args.db)
    csv_path = Path(args.archivo)

    if not csv_path.exists():
        print(f"❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)

    fecha = args.fecha or date.today().isoformat()

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saldos_bancarios_diarios (
            fecha      TEXT NOT NULL,
            cuenta_id  TEXT NOT NULL,
            saldo      REAL NOT NULL,
            PRIMARY KEY (fecha, cuenta_id)
        )
    """)

    ok = 0
    for linea in csv_path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        partes = linea.split(",")
        if len(partes) < 2:
            continue
        cuenta_id = partes[0].strip()
        try:
            monto = float(partes[1].strip().replace(".", "").replace(",", "."))
        except ValueError:
            print(f"  ⚠️  Monto inválido en línea: {linea}")
            continue

        row = conn.execute(
            "SELECT nombre FROM cuentas_bancarias WHERE cuenta_id = ?", (cuenta_id,)
        ).fetchone()
        if not row:
            print(f"  ⚠️  Cuenta '{cuenta_id}' no encontrada — omitida")
            continue

        conn.execute(
            "INSERT OR REPLACE INTO saldos_bancarios_diarios VALUES (?, ?, ?)",
            (fecha, cuenta_id, monto)
        )
        print(f"  ✅ [{fecha}] {cuenta_id} — {row[0]}: ${monto:,.0f}")
        ok += 1

    conn.commit()
    conn.close()
    print(f"\n{ok} saldo(s) registrado(s) para {fecha}")


def main():
    parser = argparse.ArgumentParser(
        prog="slep",
        description="SLEP Petorca — Sistema de Gestión Financiera",
    )
    parser.add_argument("--db", default=str(DB_DEFAULT), help="Ruta a slep.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # update
    p_update = sub.add_parser("update", help="Ingesta reportes SIGFE a SQLite")
    p_update.add_argument("--raw",         default="data/raw",  help="Carpeta con archivos SIGFE")
    p_update.add_argument("--fecha-corte", default=None,        help="Fecha de corte YYYY-MM-DD")

    # status
    sub.add_parser("status",    help="KPIs de salud financiera y alertas")

    # conciliar
    sub.add_parser("conciliar", help="Conciliación SIGFE 11102 ↔ BancoEstado")

    # disponible
    sub.add_parser("disponible", help="Disponibilidad presupuestaria por programa/FF")

    # flujo
    sub.add_parser("flujo", help="Flujo de caja histórico y proyección")

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Genera dashboard HTML (abre en navegador)")
    p_dash.add_argument("--output", default=None, help="Ruta de salida (default: reports/output/dashboard.html)")

    # saldo
    p_saldo = sub.add_parser("saldo", help="Registra saldo bancario de una cuenta")
    p_saldo.add_argument("--cuenta", required=True, help="ID de cuenta (3 dígitos, ej. 341)")
    p_saldo.add_argument("--monto",  required=True, type=float, help="Saldo en pesos")
    p_saldo.add_argument("--fecha",  default=None,  help="Fecha YYYY-MM-DD (default: hoy)")

    # saldo-lote
    p_lote = sub.add_parser("saldo-lote", help="Registra saldos desde CSV")
    p_lote.add_argument("--archivo", required=True, help="Ruta al CSV cuenta_id,monto")
    p_lote.add_argument("--fecha",   default=None,  help="Fecha YYYY-MM-DD (default: hoy)")

    args = parser.parse_args()

    cmds = {
        "update":     cmd_update,
        "status":     cmd_status,
        "conciliar":  cmd_conciliar,
        "disponible": cmd_disponible,
        "flujo":      cmd_flujo,
        "dashboard":  cmd_dashboard,
        "saldo":      cmd_saldo,
        "saldo-lote": cmd_saldo_lote,
    }
    cmds[args.cmd](args)


if __name__ == "__main__":
    main()
