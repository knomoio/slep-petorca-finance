"""
Conciliación bancaria: cuenta contable 11102 (SIGFE) ↔ saldos reales BancoEstado.

Regla de validación: suma saldos BancoEstado = saldo SIGFE 11102 al mismo corte.
Fuentes:
  - balance_snapshot  → saldo cuenta 11102 (Banco Estado contable)
  - saldos_bancarios_diarios → saldos reales por cuenta corriente
"""
import sqlite3
from pathlib import Path
import pandas as pd

DB_DEFAULT = Path("data/slep.db")


def _col(df: pd.DataFrame, *patterns: str) -> str | None:
    """Devuelve la primera columna cuyo nombre contiene alguno de los patrones."""
    for col in df.columns:
        for p in patterns:
            if p.lower() in col.lower():
                return col
    return None


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def saldo_sigfe_11102(conn: sqlite3.Connection, fecha_corte: str | None = None) -> dict:
    """
    Lee saldo final cuenta 11102 desde balance_snapshot.

    Returns:
        {"fecha_corte": str, "saldo": float} o {"saldo": None} si no hay datos.
    """
    try:
        df = pd.read_sql("SELECT * FROM balance_snapshot", conn)
    except Exception:
        return {"fecha_corte": fecha_corte, "saldo": None}

    if df.empty:
        return {"fecha_corte": fecha_corte, "saldo": None}

    col_cta   = _col(df, "cuenta_contable", "cuenta")
    col_debe  = _col(df, "saldo_final_debe", "final_debe")
    col_haber = _col(df, "saldo_final_haber", "final_haber")
    col_fecha = "_fecha_corte" if "_fecha_corte" in df.columns else _col(df, "fecha_corte", "fecha")

    if not (col_cta and col_debe and col_haber):
        return {"fecha_corte": fecha_corte, "saldo": None}

    mask = df[col_cta].astype(str).str.startswith("11102")
    df11 = df[mask].copy()
    if df11.empty:
        return {"fecha_corte": fecha_corte, "saldo": None}

    if fecha_corte and col_fecha and col_fecha in df11.columns:
        df11 = df11[df11[col_fecha].astype(str) == fecha_corte]

    saldo = (_num(df11[col_debe]) - _num(df11[col_haber])).sum()
    corte = df11[col_fecha].iloc[-1] if (col_fecha and col_fecha in df11.columns and not df11.empty) else fecha_corte

    return {"fecha_corte": str(corte), "saldo": float(saldo)}


def saldos_banco_estado(conn: sqlite3.Connection, fecha: str | None = None) -> pd.DataFrame:
    """
    Lee saldos BancoEstado desde saldos_bancarios_diarios (fecha más reciente).

    Returns:
        DataFrame con columnas: cuenta_id, nombre, programa, saldo, fecha
    """
    try:
        fecha_sql = f"AND s.fecha = '{fecha}'" if fecha else ""
        df = pd.read_sql(f"""
            SELECT s.cuenta_id, c.nombre, c.programa, s.saldo, s.fecha
            FROM saldos_bancarios_diarios s
            LEFT JOIN cuentas_bancarias c ON c.cuenta_id = s.cuenta_id
            WHERE s.fecha = (
                SELECT MAX(s2.fecha) FROM saldos_bancarios_diarios s2
                WHERE s2.cuenta_id = s.cuenta_id
            )
            {fecha_sql}
            ORDER BY c.programa, s.cuenta_id
        """, conn)
        return df
    except Exception:
        # Si la tabla no existe aún, devolver catálogo vacío
        try:
            df = pd.read_sql(
                "SELECT cuenta_id, nombre, programa FROM cuentas_bancarias ORDER BY programa, cuenta_id",
                conn
            )
            df["saldo"] = None
            df["fecha"] = None
            return df
        except Exception:
            return pd.DataFrame(columns=["cuenta_id", "nombre", "programa", "saldo", "fecha"])


def conciliar(
    db_path: Path = DB_DEFAULT,
    fecha_corte: str | None = None,
    fecha_banco: str | None = None,
) -> dict:
    """
    Ejecuta la conciliación SIGFE 11102 ↔ BancoEstado.

    Args:
        db_path:      ruta a slep.db
        fecha_corte:  corte SIGFE (YYYY-MM-DD); si None usa el último disponible
        fecha_banco:  fecha de saldos bancarios; si None usa el más reciente

    Returns:
        dict con claves:
          saldo_sigfe   – saldo cuenta 11102 según SIGFE
          saldo_banco   – suma de saldos BancoEstado
          diferencia    – saldo_sigfe - saldo_banco (0 ideal)
          estado        – "ok" | "descuadre" | "sin_datos"
          detalle       – lista de cuentas con sus saldos
    """
    conn = sqlite3.connect(db_path)
    try:
        sigfe  = saldo_sigfe_11102(conn, fecha_corte)
        df_bco = saldos_banco_estado(conn, fecha_banco)

        total_banco = float(df_bco["saldo"].sum()) if not df_bco.empty and df_bco["saldo"].notna().any() else None
        saldo_sigfe = sigfe["saldo"]

        if saldo_sigfe is not None and total_banco is not None:
            diferencia = saldo_sigfe - total_banco
            estado = "ok" if abs(diferencia) < 1_000 else "descuadre"
        else:
            diferencia = None
            estado = "sin_datos"

        return {
            "fecha_corte_sigfe": sigfe["fecha_corte"],
            "fecha_banco":       fecha_banco or (str(df_bco["fecha"].max()) if not df_bco.empty and "fecha" in df_bco.columns else None),
            "saldo_sigfe":       saldo_sigfe,
            "saldo_banco":       total_banco,
            "diferencia":        diferencia,
            "estado":            estado,
            "detalle":           df_bco.to_dict("records"),
        }
    finally:
        conn.close()


def imprimir(resultado: dict) -> None:
    def fmt(v):
        return f"${v:>22,.0f}" if v is not None else "           sin datos"

    print("\n" + "=" * 65)
    print("CONCILIACIÓN BANCARIA  —  SIGFE 11102 ↔ BancoEstado")
    print("=" * 65)
    print(f"  Corte SIGFE  : {resultado['fecha_corte_sigfe']}")
    print(f"  Fecha banco  : {resultado['fecha_banco']}")
    print()
    print(f"  Saldo SIGFE 11102      : {fmt(resultado['saldo_sigfe'])}")
    print(f"  Saldo total BancoEstado: {fmt(resultado['saldo_banco'])}")

    if resultado["diferencia"] is not None:
        dif = resultado["diferencia"]
        icono = "✅" if abs(dif) < 1_000 else "⚠️  DESCUADRE"
        print(f"  Diferencia             : {fmt(dif)}  {icono}")

    detalle = resultado.get("detalle", [])
    cuentas_con_saldo = [c for c in detalle if c.get("saldo") is not None]
    if cuentas_con_saldo:
        print(f"\n  {'ID':<6} {'Nombre':<30} {'Prog':<5} {'Saldo':>18}")
        print(f"  {'-'*6} {'-'*30} {'-'*5} {'-'*18}")
        for c in cuentas_con_saldo:
            print(
                f"  {str(c.get('cuenta_id','')):<6} "
                f"{str(c.get('nombre',''))[:30]:<30} "
                f"{str(c.get('programa','')):<5} "
                f"${float(c.get('saldo') or 0):>17,.0f}"
            )

    print(f"\n  Estado: {resultado['estado'].upper()}")
    print("=" * 65)


if __name__ == "__main__":
    import sys
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_DEFAULT
    imprimir(conciliar(db))
