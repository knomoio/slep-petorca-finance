"""
KPIs de salud financiera: deuda flotante, días de caja, pagos vencidos, alertas.

Fuentes:
  - balance_snapshot          → deuda flotante (cuentas 215xx)
  - disponibilidad_devengo    → devengado - efectivo (método alternativo)
  - saldos_bancarios_diarios  → caja total
  - chile_paga_facturas       → facturas vencidas
  - disponibilidad_compromiso → comprometido pendiente de devengar
"""
import sqlite3
from pathlib import Path
from datetime import date
import pandas as pd

DB_DEFAULT = Path("data/slep.db")

# Umbrales de alerta
DIAS_CAJA_CRITICO = 15
DIAS_CAJA_ALERTA  = 30


def _col(df: pd.DataFrame, *patterns: str) -> str | None:
    for col in df.columns:
        for p in patterns:
            if p.lower() in col.lower():
                return col
    return None


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0)


# ── Deuda flotante ────────────────────────────────────────────────────────────

def deuda_flotante(conn: sqlite3.Connection) -> dict:
    """
    Deuda flotante = Devengado − Efectivo.
    Método principal: cuentas 215xx en balance_snapshot (CxP Presupuestarios).
    Fallback: diferencia devengo−efectivo en disponibilidad_devengo.

    Returns:
        {"total": float|None, "detalle": {categoria: monto}, "fuente": str}
    """
    NOMBRES_215 = {
        "21521": "Personal",
        "21522": "Bienes y Servicios",
        "21529": "Activos No Financieros",
    }

    # Método 1: balance_snapshot
    try:
        df = pd.read_sql("SELECT * FROM balance_snapshot", conn)
        if not df.empty:
            col_cta   = _col(df, "cuenta_contable", "cuenta")
            col_debe  = _col(df, "saldo_final_debe", "final_debe")
            col_haber = _col(df, "saldo_final_haber", "final_haber")
            if col_cta and col_haber:
                mask  = df[col_cta].astype(str).str.startswith("215")
                df215 = df[mask].copy()
                if not df215.empty:
                    df215["saldo"] = _num(df215[col_haber]) - _num(df215[col_debe])
                    detalle = {
                        NOMBRES_215.get(str(row[col_cta])[:5], str(row[col_cta])[:5]): float(row["saldo"])
                        for _, row in df215.iterrows()
                    }
                    return {"total": float(df215["saldo"].sum()), "detalle": detalle, "fuente": "balance_snapshot (215xx)"}
    except Exception:
        pass

    # Método 2: disponibilidad_devengo
    try:
        df = pd.read_sql("SELECT * FROM disponibilidad_devengo", conn)
        if not df.empty:
            col_dev  = _col(df, "devengo",  "deveng")
            col_efec = _col(df, "efectivo", "efect", "pagado")
            if col_dev and col_efec:
                total = (_num(df[col_dev]) - _num(df[col_efec])).sum()
                return {"total": float(total), "detalle": {}, "fuente": "disponibilidad_devengo"}
    except Exception:
        pass

    return {"total": None, "detalle": {}, "fuente": "sin_datos"}


# ── Caja ─────────────────────────────────────────────────────────────────────

def caja_total(conn: sqlite3.Connection) -> dict:
    """Suma de saldos más recientes por cuenta en saldos_bancarios_diarios."""
    try:
        df = pd.read_sql("""
            SELECT s.cuenta_id, s.saldo, s.fecha
            FROM saldos_bancarios_diarios s
            WHERE s.fecha = (
                SELECT MAX(s2.fecha) FROM saldos_bancarios_diarios s2
                WHERE s2.cuenta_id = s.cuenta_id
            )
        """, conn)
        if not df.empty and df["saldo"].notna().any():
            return {
                "total":    float(df["saldo"].sum()),
                "fecha":    str(df["fecha"].max()),
                "n_cuentas": int(df["saldo"].notna().sum()),
            }
    except Exception:
        pass
    return {"total": None, "fecha": None, "n_cuentas": 0}


def dias_de_caja(caja: float | None, conn: sqlite3.Connection) -> float | None:
    """
    Días de caja = Caja / (Efectivo anual / días transcurridos).
    Supone que el ritmo de gasto se mantiene constante.
    """
    if not caja:
        return None
    try:
        df = pd.read_sql("SELECT * FROM disponibilidad_devengo", conn)
        if df.empty:
            return None
        col_efec = _col(df, "efectivo", "efect", "pagado")
        if not col_efec:
            return None
        total_efectivo = _num(df[col_efec]).sum()
        hoy = date.today()
        dias_transcurridos = (hoy - date(hoy.year, 1, 1)).days or 1
        gasto_diario = total_efectivo / dias_transcurridos
        return caja / gasto_diario if gasto_diario > 0 else None
    except Exception:
        return None


# ── Facturas vencidas Chile Paga ──────────────────────────────────────────────

def facturas_vencidas(conn: sqlite3.Connection) -> dict:
    """
    Facturas vencidas desde chile_paga_facturas (dias_atraso > 0).

    Returns:
        {"n": int, "monto_total": float|None, "max_dias": int, "top10": list}
    """
    try:
        df = pd.read_sql("SELECT * FROM chile_paga_facturas", conn)
        if df.empty:
            return {"n": 0, "monto_total": None, "max_dias": 0, "top10": []}

        col_dias     = _col(df, "d_as_atraso", "dias_atraso", "atraso", "vencido")
        col_monto    = _col(df, "monto",       "importe",     "valor",  "total")
        col_prov     = _col(df, "proveedor",   "raz_n",       "nombre", "razon")
        col_folio    = _col(df, "folio",       "n_mero",      "numero")

        if not col_dias:
            return {"n": 0, "monto_total": None, "max_dias": 0, "top10": []}

        df[col_dias] = _num(df[col_dias])
        venc = df[df[col_dias] > 0].copy()
        venc = venc.sort_values(col_dias, ascending=False)

        monto_total = float(_num(venc[col_monto]).sum()) if col_monto else None
        max_dias    = int(venc[col_dias].max()) if not venc.empty else 0

        top10 = []
        for _, row in venc.head(10).iterrows():
            top10.append({
                "folio":     str(row[col_folio]) if col_folio else "",
                "proveedor": str(row[col_prov])  if col_prov  else "",
                "monto":     float(_num(pd.Series([row[col_monto]]))[0]) if col_monto else None,
                "dias":      int(row[col_dias]),
            })

        return {"n": len(venc), "monto_total": monto_total, "max_dias": max_dias, "top10": top10}
    except Exception:
        return {"n": 0, "monto_total": None, "max_dias": 0, "top10": []}


# ── Compromisos pendientes ────────────────────────────────────────────────────

def comprometido_pendiente(conn: sqlite3.Connection) -> float | None:
    """Comprometido − Devengado desde disponibilidad_compromiso."""
    try:
        df = pd.read_sql("SELECT * FROM disponibilidad_compromiso", conn)
        if df.empty:
            return None
        col_comp = _col(df, "compromiso", "comp")
        col_dev  = _col(df, "devengo",    "deveng")
        if col_comp and col_dev:
            return float((_num(df[col_comp]) - _num(df[col_dev])).sum())
    except Exception:
        pass
    return None


# ── KPIs consolidados ─────────────────────────────────────────────────────────

def calcular(db_path: Path = DB_DEFAULT) -> dict:
    """Calcula todos los KPIs y genera lista de alertas."""
    conn = sqlite3.connect(db_path)
    try:
        caja   = caja_total(conn)
        df_info = deuda_flotante(conn)
        dias   = dias_de_caja(caja["total"], conn)
        venc   = facturas_vencidas(conn)
        comp   = comprometido_pendiente(conn)

        alertas = []
        if dias is not None:
            if dias < DIAS_CAJA_CRITICO:
                alertas.append({"nivel": "CRÍTICO", "msg": f"Caja cubre solo {dias:.0f} días de gasto"})
            elif dias < DIAS_CAJA_ALERTA:
                alertas.append({"nivel": "ALERTA",  "msg": f"Caja cubre {dias:.0f} días (umbral: {DIAS_CAJA_ALERTA})"})

        if venc["n"] > 0 and venc["monto_total"]:
            alertas.append({
                "nivel": "ALERTA",
                "msg":   f"{venc['n']} factura(s) vencida(s) Chile Paga: ${venc['monto_total']:,.0f} (máx {venc['max_dias']} días)",
            })

        return {
            "fecha":                date.today().isoformat(),
            "caja":                 caja,
            "deuda_flotante":       df_info,
            "dias_caja":            dias,
            "facturas_vencidas":    venc,
            "comprometido_pendiente": comp,
            "alertas":              alertas,
        }
    finally:
        conn.close()


def imprimir(db_path: Path = DB_DEFAULT) -> None:
    k = calcular(db_path)

    def fmt(v):
        return f"${v:>22,.0f}" if v is not None else "           sin datos"

    print("\n" + "=" * 62)
    print(f"SALUD FINANCIERA  —  SLEP PETORCA  [{k['fecha']}]")
    print("=" * 62)

    caja = k["caja"]
    print(f"\n  Caja BancoEstado  ({caja.get('fecha','?')}, {caja.get('n_cuentas',0)} cuentas)")
    print(f"  Total             : {fmt(caja.get('total'))}")

    dias = k["dias_caja"]
    if dias is not None:
        icono = "🔴" if dias < DIAS_CAJA_CRITICO else ("🟡" if dias < DIAS_CAJA_ALERTA else "🟢")
        print(f"  Días de caja      : {dias:>6.0f} días  {icono}")

    df_info = k["deuda_flotante"]
    print(f"\n  Deuda flotante    : {fmt(df_info.get('total'))}")
    for cat, monto in df_info.get("detalle", {}).items():
        print(f"    {cat:<24}: {fmt(monto)}")
    if df_info.get("fuente") != "sin_datos":
        print(f"    fuente: {df_info['fuente']}")

    venc = k["facturas_vencidas"]
    if venc["n"] > 0:
        print(f"\n  Facturas vencidas Chile Paga")
        print(f"    N° facturas   : {venc['n']}")
        print(f"    Monto total   : {fmt(venc.get('monto_total'))}")
        print(f"    Máx días atraso: {venc['max_dias']}")
        if venc["top10"]:
            print(f"    {'Proveedor':<35} {'Días':>6} {'Monto':>18}")
            for f in venc["top10"][:5]:
                m = fmt(f["monto"]) if f["monto"] else "   sin monto"
                print(f"    {str(f['proveedor'])[:35]:<35} {f['dias']:>6} {m}")

    comp = k.get("comprometido_pendiente")
    if comp is not None:
        print(f"\n  Comprometido pendiente: {fmt(comp)}")

    alertas = k["alertas"]
    print(f"\n{'─'*62}")
    if alertas:
        print("  ALERTAS")
        for a in alertas:
            icono = "🔴" if a["nivel"] == "CRÍTICO" else "🟡"
            print(f"  {icono} [{a['nivel']}] {a['msg']}")
    else:
        print("  ✅ Sin alertas")
    print("=" * 62)


if __name__ == "__main__":
    import sys
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_DEFAULT
    imprimir(db)
