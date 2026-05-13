"""
Flujo de caja: histórico real y proyección mensual.

Flujo real:
  - pagos  (tabla `pagos`)  → egresos
  - cobros (tabla `cobros`) → ingresos
  Agrupa por mes y muestra neto.

Proyección:
  - Saldo inicial: último saldo bancario agregado
  - Ingresos esperados: promedio mensual histórico de cobros
  - Egresos esperados:  promedio mensual histórico de pagos
  Supuesto declarado explícitamente en el output.

Calendario operacional embebido (fechas fijas SLEP Petorca):
  - Día 18:   pago líquidos P01 (cuenta 278)
  - Día 28:   pago líquidos P02 + Jardines (cuenta 391)
  - Días 10-13 mes siguiente: cotizaciones y aportes patronales
  - Días 26-30: transferencias MINEDUC (ingresos)
"""
import sqlite3
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

DB_DEFAULT = Path("data/slep.db")

CALENDARIO = {
    "egresos": {
        18: "Pago líquidos P01 (cta 278)",
        28: "Pago líquidos P02 + Jardines (cta 391)",
    },
    "egresos_mes_sig": {
        10: "Cotizaciones y aportes patronales (cta 391)",
    },
    "ingresos": {
        27: "Transferencia MINEDUC (estimado fin de mes)",
    },
}


def _col(df: pd.DataFrame, *patterns: str) -> str | None:
    for col in df.columns:
        for p in patterns:
            if p.lower() in col.lower():
                return col
    return None


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0)


def _leer_movimientos(conn: sqlite3.Connection, tabla: str, tipo: str) -> pd.DataFrame:
    """Lee pagos o cobros y devuelve DataFrame con columnas: mes, tipo, monto."""
    try:
        df = pd.read_sql(f"SELECT * FROM {tabla}", conn)
        if df.empty:
            return pd.DataFrame(columns=["mes", "tipo", "monto"])

        col_fecha = _col(df, "fecha", "date", "fech")
        col_monto = _col(df, "monto", "importe", "valor", "total", "neto")

        if not (col_fecha and col_monto):
            return pd.DataFrame(columns=["mes", "tipo", "monto"])

        df["fecha_dt"] = pd.to_datetime(df[col_fecha], errors="coerce")
        df = df.dropna(subset=["fecha_dt"])
        df["mes"]   = df["fecha_dt"].dt.to_period("M").astype(str)
        df["tipo"]  = tipo
        df["monto"] = _num(df[col_monto])
        return df[["mes", "tipo", "monto"]]
    except Exception:
        return pd.DataFrame(columns=["mes", "tipo", "monto"])


def flujo_real(conn: sqlite3.Connection, n_meses: int = 4) -> pd.DataFrame:
    """
    Flujo de caja real agrupado por mes.

    Returns:
        DataFrame con columnas: mes, ingresos, egresos, neto
    """
    df_pag = _leer_movimientos(conn, "pagos",  "egreso")
    df_cob = _leer_movimientos(conn, "cobros", "ingreso")

    df = pd.concat([df_pag, df_cob], ignore_index=True)
    if df.empty:
        return pd.DataFrame(columns=["mes", "ingresos", "egresos", "neto"])

    # Filtrar últimos n_meses
    hoy = date.today()
    mes_limite = (hoy.replace(day=1) - timedelta(days=n_meses * 30)).strftime("%Y-%m")
    df = df[df["mes"] >= mes_limite]

    pivot = df.groupby(["mes", "tipo"])["monto"].sum().unstack(fill_value=0).reset_index()
    pivot.columns.name = None

    if "ingreso" not in pivot.columns:
        pivot["ingreso"] = 0.0
    if "egreso" not in pivot.columns:
        pivot["egreso"] = 0.0

    pivot = pivot.rename(columns={"ingreso": "ingresos", "egreso": "egresos"})
    pivot["neto"] = pivot["ingresos"] - pivot["egresos"]
    return pivot.sort_values("mes")[["mes", "ingresos", "egresos", "neto"]]


def _saldo_inicial(conn: sqlite3.Connection) -> float:
    """Último saldo bancario total disponible."""
    try:
        row = pd.read_sql("""
            SELECT SUM(saldo) AS total
            FROM saldos_bancarios_diarios
            WHERE fecha = (SELECT MAX(fecha) FROM saldos_bancarios_diarios)
        """, conn).iloc[0]["total"]
        return float(row) if row is not None else 0.0
    except Exception:
        return 0.0


def proyeccion(conn: sqlite3.Connection, n_meses: int = 3) -> list[dict]:
    """
    Proyección mensual de caja.

    Supuestos (declarados en cada fila del output):
    1. Ingresos = promedio mensual histórico de cobros (últimos 6 meses)
    2. Egresos  = promedio mensual histórico de pagos  (últimos 6 meses)
    3. Saldo inicial = suma saldos BancoEstado más recientes

    Returns:
        Lista de dicts con: mes, saldo_inicial, ingresos, egresos, neto, saldo_final
    """
    df_real = flujo_real(conn, n_meses=6)

    avg_ing = float(df_real["ingresos"].mean()) if not df_real.empty and df_real["ingresos"].any() else 0.0
    avg_egr = float(df_real["egresos"].mean())  if not df_real.empty and df_real["egresos"].any()  else 0.0

    saldo = _saldo_inicial(conn)
    hoy   = date.today()

    meses = []
    for i in range(1, n_meses + 1):
        primer_dia = (hoy.replace(day=1) + timedelta(days=32 * i)).replace(day=1)
        mes_str    = primer_dia.strftime("%Y-%m")
        neto       = avg_ing - avg_egr
        saldo_fin  = saldo + neto

        meses.append({
            "mes":                mes_str,
            "saldo_inicial":      saldo,
            "ingresos_estimados": avg_ing,
            "egresos_estimados":  avg_egr,
            "flujo_neto":         neto,
            "saldo_final":        saldo_fin,
            "supuesto":           "promedio_historico_6m",
        })
        saldo = saldo_fin

    return meses


def imprimir(db_path: Path = DB_DEFAULT, n_hist: int = 4, n_proy: int = 3) -> None:
    conn = sqlite3.connect(db_path)
    try:
        print("\n" + "=" * 74)
        print("FLUJO DE CAJA  —  SLEP PETORCA")
        print("=" * 74)

        # ── Histórico ──
        df = flujo_real(conn, n_hist)
        if not df.empty:
            print(f"\n  FLUJO REAL (últimos {n_hist} meses)")
            print(f"  {'Mes':<9} {'Ingresos':>18} {'Egresos':>18} {'Neto':>18}")
            print(f"  {'─'*9} {'─'*18} {'─'*18} {'─'*18}")
            for _, r in df.iterrows():
                print(
                    f"  {r['mes']:<9} "
                    f"${r['ingresos']:>17,.0f} "
                    f"${r['egresos']:>17,.0f} "
                    f"${r['neto']:>17,.0f}"
                )
        else:
            print("\n  (Sin datos de pagos/cobros SIGFE — ejecute el pipeline primero)")

        # ── Proyección ──
        proy = proyeccion(conn, n_proy)
        if proy and (proy[0]["ingresos_estimados"] or proy[0]["saldo_inicial"]):
            print(f"\n  PROYECCIÓN — próximos {n_proy} meses")
            print(f"  Supuesto: promedio histórico de ingresos y egresos (últimos 6m)")
            print(f"\n  {'Mes':<9} {'Saldo Ini':>16} {'+ Ingresos':>16} {'− Egresos':>16} {'Saldo Fin':>16}")
            print(f"  {'─'*9} {'─'*16} {'─'*16} {'─'*16} {'─'*16}")
            for p in proy:
                alerta = " ⚠️" if p["saldo_final"] < 0 else ""
                print(
                    f"  {p['mes']:<9} "
                    f"${p['saldo_inicial']:>15,.0f} "
                    f"${p['ingresos_estimados']:>15,.0f} "
                    f"${p['egresos_estimados']:>15,.0f} "
                    f"${p['saldo_final']:>15,.0f}{alerta}"
                )

        # ── Calendario operacional ──
        print(f"\n  CALENDARIO MENSUAL OPERACIONAL")
        print(f"  {'Día':<6} {'Evento'}")
        print(f"  {'─'*6} {'─'*50}")
        for dia, desc in CALENDARIO["egresos"].items():
            print(f"  {dia:<6} [EGRESO]  {desc}")
        for dia, desc in CALENDARIO["ingresos"].items():
            print(f"  {dia:<6} [INGRESO] {desc}")
        for dia, desc in CALENDARIO["egresos_mes_sig"].items():
            print(f"  {dia:<6} [EGRESO]  {desc} (mes siguiente)")

        print("=" * 74)
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_DEFAULT
    imprimir(db)
