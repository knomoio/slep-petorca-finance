"""
Dashboard HTML interactivo — SLEP Petorca.

Genera reports/output/dashboard.html con:
  - KPI cards: caja, días de caja, deuda flotante, ejecución %
  - Gráfico ejecución por subtítulo (Ley Vigente vs Devengado vs Efectivo)
  - Gráfico caja real por cuenta-FF
  - Gráfico flujo de caja histórico (ingresos / egresos / saldo)
  - Tabla facturas vencidas Chile Paga
  - Panel de alertas

Uso:
    python -m reports.dashboard
    python cli.py dashboard
"""
import sqlite3
import json
from datetime import date
from pathlib import Path

DB_DEFAULT    = Path("data/slep.db")
OUTPUT_DIR    = Path("reports/output")
OUTPUT_FILE   = OUTPUT_DIR / "dashboard.html"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _col(df_cols: list[str], *patterns: str) -> str | None:
    for col in df_cols:
        for p in patterns:
            if p.lower() in col.lower():
                return col
    return None


def _fmt_clp(v) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):,.0f}".replace(",", ".")
    except Exception:
        return "—"


def _fmt_clp_M(v) -> str:
    """Formatea en millones con 1 decimal."""
    if v is None:
        return "—"
    try:
        return f"${float(v)/1_000_000:.1f}M"
    except Exception:
        return "—"


# ── Lectores de datos ─────────────────────────────────────────────────────────

def _leer(conn, tabla: str):
    import pandas as pd
    try:
        return pd.read_sql(f"SELECT * FROM {tabla}", conn)
    except Exception:
        import pandas as pd
        return pd.DataFrame()


def datos_kpis(conn) -> dict:
    import pandas as pd

    # Caja
    caja_total, caja_fecha = None, None
    try:
        r = pd.read_sql("""
            SELECT SUM(saldo) AS total,
                   MAX(fecha) AS fecha
            FROM saldos_bancarios_diarios
            WHERE fecha = (SELECT MAX(fecha) FROM saldos_bancarios_diarios)
        """, conn).iloc[0]
        caja_total = float(r["total"]) if r["total"] is not None else None
        caja_fecha = str(r["fecha"]) if r["fecha"] is not None else None
    except Exception:
        pass

    # Deuda flotante desde balance_snapshot cuentas 215xx
    deuda_flotante = None
    try:
        df = _leer(conn, "balance_snapshot")
        if not df.empty:
            col_cta   = _col(list(df.columns), "cuenta_contable", "cuenta")
            col_debe  = _col(list(df.columns), "saldo_final_debe",  "final_debe")
            col_haber = _col(list(df.columns), "saldo_final_haber", "final_haber")
            if col_cta and col_haber:
                mask = df[col_cta].astype(str).str.startswith("215")
                df215 = df[mask]
                if not df215.empty:
                    import numpy as np
                    deuda_flotante = float(
                        (pd.to_numeric(df215[col_haber], errors="coerce").fillna(0) -
                         pd.to_numeric(df215[col_debe],  errors="coerce").fillna(0)).sum()
                    )
    except Exception:
        pass

    # Ejecución presupuestaria (% devengado vs ley vigente)
    ejec_pct, ley_vigente, devengado = None, None, None
    try:
        df = _leer(conn, "disponibilidad_devengo")
        if not df.empty:
            col_ley = _col(list(df.columns), "ley_vigente", "ley")
            col_dev = _col(list(df.columns), "devengo", "deveng")
            if col_ley and col_dev:
                import pandas as pd
                lv  = pd.to_numeric(df[col_ley], errors="coerce").fillna(0).sum()
                dev = pd.to_numeric(df[col_dev], errors="coerce").fillna(0).sum()
                ley_vigente = float(lv)
                devengado   = float(dev)
                ejec_pct    = dev / lv * 100 if lv else None
    except Exception:
        pass

    # Días de caja
    dias_caja = None
    if caja_total and devengado:
        hoy = date.today()
        dias_transcurridos = (hoy - date(hoy.year, 1, 1)).days or 1
        gasto_diario = devengado / dias_transcurridos
        if gasto_diario > 0:
            dias_caja = caja_total / gasto_diario

    return {
        "caja_total":    caja_total,
        "caja_fecha":    caja_fecha,
        "deuda_flotante": deuda_flotante,
        "ejec_pct":      ejec_pct,
        "ley_vigente":   ley_vigente,
        "devengado":     devengado,
        "dias_caja":     dias_caja,
    }


def datos_ejecucion_subtitulo(conn) -> dict:
    """Ejecución por subtítulo: Ley Vigente, Devengado, Efectivo."""
    import pandas as pd
    NOMBRES = {
        "21": "Personal", "22": "Bienes/Servicios", "23": "Seg. Social",
        "25": "Íntegros", "29": "Activos", "31": "Inversión",
    }
    try:
        df = _leer(conn, "disponibilidad_devengo")
        if df.empty:
            return {}
        col_st   = _col(list(df.columns), "cat_logo_02", "catalogo_02", "cat02", "subtitulo")
        col_ley  = _col(list(df.columns), "ley_vigente", "ley")
        col_dev  = _col(list(df.columns), "devengo",     "deveng")
        col_efec = _col(list(df.columns), "efectivo",    "efect", "pagado")
        if not (col_st and col_ley):
            return {}

        df["_st"] = df[col_st].astype(str).str[:2]
        df["_ley"] = pd.to_numeric(df[col_ley], errors="coerce").fillna(0)
        df["_dev"] = pd.to_numeric(df[col_dev], errors="coerce").fillna(0) if col_dev else 0
        df["_efc"] = pd.to_numeric(df[col_efec], errors="coerce").fillna(0) if col_efec else 0

        grp = df.groupby("_st")[["_ley", "_dev", "_efc"]].sum()
        grp = grp[grp["_ley"] > 0]

        return {
            "labels":   [NOMBRES.get(idx, f"ST {idx}") for idx in grp.index],
            "ley":      [round(v / 1e6, 1) for v in grp["_ley"]],
            "devengado":[round(v / 1e6, 1) for v in grp["_dev"]],
            "efectivo": [round(v / 1e6, 1) for v in grp["_efc"]],
        }
    except Exception:
        return {}


def datos_caja_ff(conn) -> dict:
    """Saldo por cuenta-FF (barras horizontales)."""
    import pandas as pd
    try:
        df = pd.read_sql("""
            SELECT s.cuenta_id, c.nombre, c.programa, s.saldo
            FROM saldos_bancarios_diarios s
            INNER JOIN cuentas_bancarias c ON c.cuenta_id = s.cuenta_id
            WHERE s.fecha = (
                SELECT MAX(s2.fecha) FROM saldos_bancarios_diarios s2
                WHERE s2.cuenta_id = s.cuenta_id
            )
            ORDER BY s.saldo DESC
        """, conn)
        if df.empty or df["saldo"].isna().all():
            return {}
        return {
            "labels":   [f"[{r['cuenta_id']}] {r['nombre'][:28]}" for _, r in df.iterrows()],
            "valores":  [round(float(r["saldo"]) / 1e6, 2) for _, r in df.iterrows()],
            "colores":  ["#1f6aa5" if r["programa"] == "P01" else "#2e8b57" for _, r in df.iterrows()],
        }
    except Exception:
        return {}


def datos_flujo_historico(conn) -> dict:
    """Ingresos y egresos reales por mes."""
    import pandas as pd
    meses, ingresos, egresos = [], [], []
    try:
        for tabla, col_tipo, signo in [("cobros", "ingreso", 1), ("pagos", "egreso", -1)]:
            df = _leer(conn, tabla)
            if df.empty:
                continue
            col_fecha = _col(list(df.columns), "fecha", "date")
            col_monto = _col(list(df.columns), "monto", "importe", "valor", "total", "neto")
            if not (col_fecha and col_monto):
                continue
            df["_dt"] = pd.to_datetime(df[col_fecha], errors="coerce")
            df["_mes"] = df["_dt"].dt.to_period("M").astype(str)
            df["_m"]   = pd.to_numeric(df[col_monto], errors="coerce").fillna(0)
            grp = df.groupby("_mes")["_m"].sum()
            if col_tipo == "ingreso":
                for mes, v in grp.items():
                    if mes not in meses:
                        meses.append(mes)
                        ingresos.append(0)
                        egresos.append(0)
                    ingresos[meses.index(mes)] = round(float(v) / 1e6, 2)
            else:
                for mes, v in grp.items():
                    if mes not in meses:
                        meses.append(mes)
                        ingresos.append(0)
                        egresos.append(0)
                    egresos[meses.index(mes)] = round(float(v) / 1e6, 2)
    except Exception:
        pass

    if not meses:
        return {}

    # Ordenar por mes
    orden = sorted(range(len(meses)), key=lambda i: meses[i])
    meses    = [meses[i]    for i in orden]
    ingresos = [ingresos[i] for i in orden]
    egresos  = [egresos[i]  for i in orden]
    saldos   = []
    acum = 0.0
    for ing, egr in zip(ingresos, egresos):
        acum += ing - egr
        saldos.append(round(acum, 2))

    return {"meses": meses, "ingresos": ingresos, "egresos": egresos, "saldos": saldos}


def datos_facturas_vencidas(conn) -> list[dict]:
    """Top 10 facturas vencidas Chile Paga."""
    import pandas as pd
    try:
        df = _leer(conn, "chile_paga_facturas")
        if df.empty:
            return []
        col_dias  = _col(list(df.columns), "d_as_atraso", "dias_atraso", "atraso", "vencido")
        col_monto = _col(list(df.columns), "monto",       "importe",     "valor",  "total")
        col_prov  = _col(list(df.columns), "proveedor",   "raz_n",       "nombre", "razon")
        col_folio = _col(list(df.columns), "folio",       "n_mero",      "numero")
        if not col_dias:
            return []
        df["_dias"] = pd.to_numeric(df[col_dias], errors="coerce").fillna(0)
        venc = df[df["_dias"] > 0].sort_values("_dias", ascending=False).head(10)
        rows = []
        for _, r in venc.iterrows():
            rows.append({
                "folio":     str(r[col_folio]) if col_folio else "—",
                "proveedor": str(r[col_prov])[:40]  if col_prov  else "—",
                "monto":     _fmt_clp(r[col_monto])  if col_monto else "—",
                "dias":      int(r["_dias"]),
            })
        return rows
    except Exception:
        return []


def datos_alertas(kpis: dict, facturas: list[dict]) -> list[dict]:
    alertas = []
    dias = kpis.get("dias_caja")
    if dias is not None:
        if dias < 15:
            alertas.append({"nivel": "critico", "msg": f"Caja cubre solo {dias:.0f} días de gasto"})
        elif dias < 30:
            alertas.append({"nivel": "alerta",  "msg": f"Caja cubre {dias:.0f} días de gasto (umbral: 30)"})
    if facturas:
        max_dias = max(f["dias"] for f in facturas)
        alertas.append({"nivel": "alerta",
                         "msg": f"{len(facturas)} factura(s) vencida(s) en Chile Paga (máx {max_dias} días)"})
    if kpis.get("caja_total") is None:
        alertas.append({"nivel": "info", "msg": "Sin saldos bancarios cargados — use 'python cli.py saldo'"})
    if kpis.get("ley_vigente") is None:
        alertas.append({"nivel": "info", "msg": "Sin datos SIGFE — ejecute 'python cli.py update'"})
    return alertas


# ── Generador HTML ────────────────────────────────────────────────────────────

def generar(db_path: Path = DB_DEFAULT, output: Path = OUTPUT_FILE) -> Path:
    conn = sqlite3.connect(db_path)
    try:
        kpis       = datos_kpis(conn)
        ejec_st    = datos_ejecucion_subtitulo(conn)
        caja_ff    = datos_caja_ff(conn)
        flujo_hist = datos_flujo_historico(conn)
        facturas   = datos_facturas_vencidas(conn)
        alertas    = datos_alertas(kpis, facturas)
    finally:
        conn.close()

    hoy  = date.today().isoformat()
    dias = kpis.get("dias_caja")
    dias_color = "#dc3545" if (dias and dias < 15) else ("#fd7e14" if (dias and dias < 30) else "#198754")
    dias_str   = f"{dias:.0f}" if dias else "—"

    # Serializar datos para Chart.js
    ejec_json   = json.dumps(ejec_st,    ensure_ascii=False)
    caja_json   = json.dumps(caja_ff,    ensure_ascii=False)
    flujo_json  = json.dumps(flujo_hist, ensure_ascii=False)

    # Filas de tabla facturas
    filas_facturas = ""
    for f in facturas:
        color_dias = "#dc3545" if f["dias"] > 60 else ("#fd7e14" if f["dias"] > 30 else "#6c757d")
        filas_facturas += f"""
        <tr>
          <td>{f["folio"]}</td>
          <td>{f["proveedor"]}</td>
          <td style="text-align:right">{f["monto"]}</td>
          <td style="text-align:center;color:{color_dias};font-weight:600">{f["dias"]}</td>
        </tr>"""
    if not facturas:
        filas_facturas = '<tr><td colspan="4" style="text-align:center;color:#6c757d">Sin facturas vencidas</td></tr>'

    # Alertas HTML
    alertas_html = ""
    for a in alertas:
        icon  = {"critico": "🔴", "alerta": "🟡", "info": "🔵"}.get(a["nivel"], "ℹ️")
        color = {"critico": "#f8d7da", "alerta": "#fff3cd", "info": "#cfe2ff"}.get(a["nivel"], "#e2e3e5")
        alertas_html += f'<div class="alerta" style="background:{color}">{icon} {a["msg"]}</div>'
    if not alertas:
        alertas_html = '<div class="alerta" style="background:#d1e7dd">✅ Sin alertas — posición financiera normal</div>'

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SLEP Petorca — Dashboard Financiero</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f2f5; color: #212529; font-size: 14px; }}
  header {{ background: #1f2d3d; color: white; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }}
  header h1 {{ font-size: 20px; font-weight: 600; }}
  header .fecha {{ font-size: 12px; opacity: 0.7; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
  .grid-kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }}
  .kpi {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); border-left: 4px solid #1f6aa5; }}
  .kpi .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: #6c757d; margin-bottom: 6px; }}
  .kpi .valor {{ font-size: 24px; font-weight: 700; }}
  .kpi .sub {{ font-size: 11px; color: #6c757d; margin-top: 4px; }}
  .grid-charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .card {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .card h3 {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; color: #495057; margin-bottom: 16px; border-bottom: 1px solid #e9ecef; padding-bottom: 10px; }}
  .grid-bottom {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #f8f9fa; text-align: left; padding: 8px 10px; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }}
  tr:hover td {{ background: #f8f9fa; }}
  .alerta {{ padding: 10px 14px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; }}
  .sin-datos {{ color: #6c757d; font-style: italic; text-align: center; padding: 30px; }}
  .badge-p01 {{ background:#cce5ff; color:#004085; padding:2px 8px; border-radius:10px; font-size:11px; }}
  .badge-p02 {{ background:#d4edda; color:#155724; padding:2px 8px; border-radius:10px; font-size:11px; }}
  @media (max-width: 900px) {{
    .grid-kpis {{ grid-template-columns: repeat(2,1fr); }}
    .grid-charts, .grid-bottom {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>SLEP Petorca — Dashboard Financiero</h1>
    <div>Servicio Local de Educación Pública de Petorca · Código 0949</div>
  </div>
  <div class="fecha">Generado: {hoy} &nbsp;|&nbsp; Fuente: SIGFE 2.0 + BancoEstado</div>
</header>

<div class="container">

  <!-- KPIs -->
  <div class="grid-kpis">
    <div class="kpi" style="border-color:#1f6aa5">
      <div class="label">Caja BancoEstado</div>
      <div class="valor">{_fmt_clp_M(kpis.get("caja_total"))}</div>
      <div class="sub">Al {kpis.get("caja_fecha") or "sin datos"}</div>
    </div>
    <div class="kpi" style="border-color:{dias_color}">
      <div class="label">Días de Caja</div>
      <div class="valor" style="color:{dias_color}">{dias_str}</div>
      <div class="sub">días de gasto proyectado</div>
    </div>
    <div class="kpi" style="border-color:#dc3545">
      <div class="label">Deuda Flotante</div>
      <div class="valor">{_fmt_clp_M(kpis.get("deuda_flotante"))}</div>
      <div class="sub">Devengado − Efectivo (ctas 215xx)</div>
    </div>
    <div class="kpi" style="border-color:#6f42c1">
      <div class="label">Ejecución Gastos</div>
      <div class="valor">{f"{kpis['ejec_pct']:.1f}%" if kpis.get("ejec_pct") else "—"}</div>
      <div class="sub">Devengado / Ley Vigente · Lineal {round(date.today().timetuple().tm_yday/3.65, 1)}%</div>
    </div>
  </div>

  <!-- Gráficos superiores -->
  <div class="grid-charts">
    <div class="card">
      <h3>Ejecución Presupuestaria por Subtítulo (MM$)</h3>
      {"<canvas id='chartEjec'></canvas>" if ejec_st else '<div class="sin-datos">Sin datos SIGFE cargados</div>'}
    </div>
    <div class="card">
      <h3>Caja por Fuente de Financiamiento (MM$)</h3>
      {"<canvas id='chartCaja'></canvas>" if caja_ff else '<div class="sin-datos">Sin saldos bancarios — use: python cli.py saldo</div>'}
    </div>
  </div>

  <!-- Flujo de caja -->
  <div class="card" style="margin-bottom:20px">
    <h3>Flujo de Caja Histórico (MM$)</h3>
    {"<canvas id='chartFlujo' height='80'></canvas>" if flujo_hist else '<div class="sin-datos">Sin datos de pagos/cobros SIGFE</div>'}
  </div>

  <!-- Tabla + Alertas -->
  <div class="grid-bottom">
    <div class="card">
      <h3>Facturas Vencidas — Chile Paga (Top 10)</h3>
      <table>
        <thead><tr><th>Folio</th><th>Proveedor</th><th>Monto</th><th>Días</th></tr></thead>
        <tbody>{filas_facturas}</tbody>
      </table>
    </div>
    <div class="card">
      <h3>Alertas y Estado</h3>
      {alertas_html}
      <br>
      <div style="font-size:12px;color:#6c757d;border-top:1px solid #eee;padding-top:12px">
        <strong>Datos disponibles:</strong><br>
        {"✅" if kpis.get("ley_vigente") else "❌"} SIGFE (ejecución presupuestaria)<br>
        {"✅" if kpis.get("caja_total") else "❌"} Saldos BancoEstado<br>
        {"✅" if flujo_hist else "❌"} Pagos/Cobros SIGFE (flujo histórico)<br>
        {"✅" if facturas else "—"} Facturas Chile Paga
      </div>
    </div>
  </div>

</div><!-- /container -->

<script>
const ejec  = {ejec_json};
const caja  = {caja_json};
const flujo = {flujo_json};

// Chart 1: Ejecución por subtítulo
if (ejec && ejec.labels && document.getElementById('chartEjec')) {{
  new Chart(document.getElementById('chartEjec'), {{
    type: 'bar',
    data: {{
      labels: ejec.labels,
      datasets: [
        {{ label: 'Ley Vigente', data: ejec.ley,      backgroundColor: '#adb5bd' }},
        {{ label: 'Devengado',   data: ejec.devengado, backgroundColor: '#1f6aa5' }},
        {{ label: 'Efectivo',    data: ejec.efectivo,  backgroundColor: '#2e8b57' }},
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ position: 'top' }} }},
      scales: {{
        y: {{ title: {{ display: true, text: 'MM$' }} }}
      }}
    }}
  }});
}}

// Chart 2: Caja por FF (horizontal bars)
if (caja && caja.labels && document.getElementById('chartCaja')) {{
  new Chart(document.getElementById('chartCaja'), {{
    type: 'bar',
    data: {{
      labels: caja.labels,
      datasets: [{{ label: 'Saldo MM$', data: caja.valores, backgroundColor: caja.colores }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ title: {{ display: true, text: 'MM$' }} }} }}
    }}
  }});
}}

// Chart 3: Flujo histórico
if (flujo && flujo.meses && document.getElementById('chartFlujo')) {{
  new Chart(document.getElementById('chartFlujo'), {{
    type: 'bar',
    data: {{
      labels: flujo.meses,
      datasets: [
        {{ label: 'Ingresos',  data: flujo.ingresos, backgroundColor: '#2e8b57' }},
        {{ label: 'Egresos',   data: flujo.egresos,  backgroundColor: '#dc3545' }},
        {{ label: 'Saldo acum.',data: flujo.saldos,  type: 'line',
          borderColor: '#1f6aa5', backgroundColor: 'transparent',
          tension: 0.3, yAxisID: 'y1' }},
      ]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index' }},
      plugins: {{ legend: {{ position: 'top' }} }},
      scales: {{
        y:  {{ title: {{ display: true, text: 'MM$' }} }},
        y1: {{ position: 'right', title: {{ display: true, text: 'Saldo acum. MM$' }},
               grid: {{ drawOnChartArea: false }} }}
      }}
    }}
  }});
}}
</script>
</body>
</html>"""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard generado: {output.resolve()}")
    return output


if __name__ == "__main__":
    import sys
    db  = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_DEFAULT
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else OUTPUT_FILE
    generar(db, out)
