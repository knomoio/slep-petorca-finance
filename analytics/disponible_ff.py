"""
Disponibilidad presupuestaria por Fuente de Financiamiento (FF) y Programa.

SIGFE no tiene FF como dimensión → la FF se identifica por cuenta bancaria.
Este módulo une:
  - disponibilidad_devengo / disponibilidad_compromiso  → disponible presupuestario
  - saldos_bancarios_diarios + cuentas_bancarias        → caja real por FF
  - cuentas_bancarias                                   → catálogo FF / Programa

Salida principal: tabla por Programa y Subtítulo con
  Ley Vigente | Comprometido | Devengado | Efectivo | Disponible | Caja
"""
import sqlite3
from pathlib import Path
import pandas as pd

DB_DEFAULT = Path("data/slep.db")

SUBTITULOS = {
    "21": "Gastos en Personal",
    "22": "Bienes y Servicios",
    "23": "Prest. Seg. Social",
    "25": "Íntegros al Fisco",
    "29": "Adq. Activos No Fin.",
    "31": "Iniciativas de Inversión",
    "05": "Transferencias Ctes. (ing)",
    "08": "Otros Ingresos",
    "09": "Aporte Fiscal",
    "12": "Recuperación Préstamos",
    "13": "Transf. Capital (ing)",
}


def _col(df: pd.DataFrame, *patterns: str) -> str | None:
    for col in df.columns:
        for p in patterns:
            if p.lower() in col.lower():
                return col
    return None


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0)


def disponible_por_subtitulo(
    conn: sqlite3.Connection,
    etapa: str = "devengo",
) -> pd.DataFrame:
    """
    Disponibilidad presupuestaria agrupada por Programa y Subtítulo.

    Args:
        etapa: "devengo" | "compromiso" | "requerimiento"

    Returns:
        DataFrame con: programa, subtitulo_cod, subtitulo, ley_vigente,
                       comprometido, devengado, efectivo, disponible
    """
    tabla = {
        "devengo":       "disponibilidad_devengo",
        "compromiso":    "disponibilidad_compromiso",
        "requerimiento": "disponibilidad_requerimiento",
    }.get(etapa, "disponibilidad_devengo")

    try:
        df = pd.read_sql(f"SELECT * FROM {tabla}", conn)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Columnas clave — los nombres exactos dependen de la versión SIGFE
    col_prog = _col(df, "cat_logo_01", "catalogo_01", "cat01", "programa")
    col_st   = _col(df, "cat_logo_02", "catalogo_02", "cat02", "subtitulo")
    col_ley  = _col(df, "ley_vigente", "ley")
    col_comp = _col(df, "compromiso",  "comp")
    col_dev  = _col(df, "devengo",     "deveng")
    col_efec = _col(df, "efectivo",    "efect", "pagado")
    col_disp = _col(df, "disponible",  "disp")

    group_cols = [c for c in [col_prog, col_st] if c]
    if not group_cols:
        return pd.DataFrame()

    rows = []
    for keys, grp in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)

        prog = str(keys[0])[:5] if col_prog else ""
        st   = str(keys[1])[:5] if (col_st and len(keys) > 1) else ""

        ley  = _num(grp[col_ley]).sum()  if col_ley  else 0.0
        comp = _num(grp[col_comp]).sum() if col_comp else 0.0
        dev  = _num(grp[col_dev]).sum()  if col_dev  else 0.0
        efec = _num(grp[col_efec]).sum() if col_efec else 0.0
        disp = _num(grp[col_disp]).sum() if col_disp else (ley - dev)

        rows.append({
            "programa":      prog,
            "subtitulo_cod": st[:2],
            "subtitulo":     SUBTITULOS.get(st[:2], st),
            "ley_vigente":   ley,
            "comprometido":  comp,
            "devengado":     dev,
            "efectivo":      efec,
            "disponible":    disp,
        })

    return pd.DataFrame(rows)


def caja_por_ff(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Saldo más reciente por cuenta-FF desde saldos_bancarios_diarios.
    Si la tabla está vacía devuelve el catálogo con saldo=None.
    """
    try:
        df = pd.read_sql("""
            SELECT s.cuenta_id, c.nombre, c.programa, c.uso_permitido,
                   s.saldo, s.fecha
            FROM saldos_bancarios_diarios s
            INNER JOIN cuentas_bancarias c ON c.cuenta_id = s.cuenta_id
            WHERE s.fecha = (
                SELECT MAX(s2.fecha)
                FROM saldos_bancarios_diarios s2
                WHERE s2.cuenta_id = s.cuenta_id
            )
            ORDER BY c.programa, s.cuenta_id
        """, conn)
        if not df.empty:
            return df
    except Exception:
        pass

    # Fallback: catálogo sin saldos
    try:
        df = pd.read_sql(
            "SELECT cuenta_id, nombre, programa, uso_permitido FROM cuentas_bancarias ORDER BY programa, cuenta_id",
            conn,
        )
        df["saldo"] = None
        df["fecha"] = None
        return df
    except Exception:
        return pd.DataFrame(columns=["cuenta_id", "nombre", "programa", "uso_permitido", "saldo", "fecha"])


def resumen(conn: sqlite3.Connection) -> dict:
    """
    Resumen ejecutivo: totales P01/P02 y caja por FF.
    """
    df_ppto = disponible_por_subtitulo(conn)
    df_caja = caja_por_ff(conn)

    def totales_prog(prog: str) -> dict:
        if df_ppto.empty or "programa" not in df_ppto.columns:
            return {}
        sub = df_ppto[df_ppto["programa"].str.startswith(prog, na=False)]
        if sub.empty:
            return {}
        return {k: float(sub[k].sum()) for k in ["ley_vigente", "comprometido", "devengado", "efectivo", "disponible"]}

    def caja_prog(prog: str) -> float | None:
        if df_caja.empty or "programa" not in df_caja.columns:
            return None
        sub = df_caja[df_caja["programa"] == prog]
        if sub.empty or sub["saldo"].isna().all():
            return None
        return float(sub["saldo"].sum())

    return {
        "P01": {**totales_prog("P01"), "caja_banco": caja_prog("P01")},
        "P02": {**totales_prog("P02"), "caja_banco": caja_prog("P02")},
        "ppto_detalle": df_ppto.to_dict("records"),
        "caja_detalle": df_caja.to_dict("records"),
    }


def imprimir(db_path: Path = DB_DEFAULT) -> None:
    conn = sqlite3.connect(db_path)
    try:
        r = resumen(conn)

        def fmt(v):
            return f"${v:>22,.0f}" if v is not None else "           sin datos"

        print("\n" + "=" * 72)
        print("DISPONIBILIDAD PRESUPUESTARIA Y CAJA  —  SLEP PETORCA")
        print("=" * 72)

        for prog in ["P01", "P02"]:
            d = r[prog]
            print(f"\n  ── {prog} ──")
            if d.get("ley_vigente"):
                lv  = d["ley_vigente"]
                dev = d.get("devengado", 0)
                pct = dev / lv * 100 if lv else 0
                print(f"  Ley Vigente          : {fmt(lv)}")
                print(f"  Comprometido         : {fmt(d.get('comprometido'))}")
                print(f"  Devengado            : {fmt(dev)}  ({pct:.1f}%)")
                print(f"  Efectivo (pagado)    : {fmt(d.get('efectivo'))}")
                print(f"  Disponible (devengo) : {fmt(d.get('disponible'))}")
            else:
                print("  (Sin datos presupuestarios SIGFE)")
            print(f"  Caja BancoEstado     : {fmt(d.get('caja_banco'))}")

        # Detalle subtítulos
        ppto = r.get("ppto_detalle", [])
        if ppto:
            print(f"\n{'─'*72}")
            print(f"  {'Prog':<5} {'Subtítulo':<26} {'Ley Vigente':>16} {'Devengado':>16} {'Disponible':>16}")
            print(f"  {'─'*5} {'─'*26} {'─'*16} {'─'*16} {'─'*16}")
            for row in ppto:
                print(
                    f"  {str(row.get('programa','')):<5} "
                    f"{str(row.get('subtitulo',''))[:26]:<26} "
                    f"${float(row.get('ley_vigente') or 0):>15,.0f} "
                    f"${float(row.get('devengado') or 0):>15,.0f} "
                    f"${float(row.get('disponible') or 0):>15,.0f}"
                )

        # Caja por FF
        caja = [c for c in r.get("caja_detalle", []) if c.get("saldo") is not None]
        if caja:
            print(f"\n{'─'*72}")
            print(f"  {'ID':<6} {'Cuenta-FF':<30} {'Prog':<5} {'Saldo':>18}")
            print(f"  {'─'*6} {'─'*30} {'─'*5} {'─'*18}")
            for c in caja:
                print(
                    f"  {str(c.get('cuenta_id','')):<6} "
                    f"{str(c.get('nombre',''))[:30]:<30} "
                    f"{str(c.get('programa','')):<5} "
                    f"${float(c.get('saldo') or 0):>17,.0f}"
                )

        print("=" * 72)
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_DEFAULT
    imprimir(db)
