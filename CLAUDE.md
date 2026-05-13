# SLEP Petorca — Sistema de Gestión Financiera Integrada

Este proyecto construye un asistente financiero-contable para el **Servicio Local de Educación Pública de Petorca (SLEP Petorca)**, código institucional 0949. Integra datos de SIGFE 2.0, BancoEstado y CasChile (remuneraciones) en una base de datos local con dashboard tiempo real, alertas y proyecciones.

## Contexto institucional

**SLEP Petorca** funciona con dos programas presupuestarios:
- **Programa 01 — Gastos Administrativos Petorca**: financiado por Aporte Fiscal Libre ($4.450M Ley Vigente 2026 incluyendo modificaciones). Gasta en personal administrativo (76 personas), bienes y servicios, y activos. Cuentas bancarias: 21909000260 (Resto) y 21909000278 (Remuneraciones P01).
- **Programa 02 — Servicio Educativo Petorca**: financiado por múltiples subvenciones del MINEDUC y JUNJI ($38.063M Ley Vigente 2026, $42.890M total con ingresos). Gasta en remuneraciones docentes/asistentes, jardines, bienes/servicios de establecimientos. Todas las demás cuentas bancarias.

Las **Fuentes de Financiamiento (FF)** del SLEP están restringidas en su uso por normativa MINEDUC. Cada FF se identifica con una cuenta bancaria distinta. SIGFE **no tiene FF como dimensión presupuestaria**: la FF se identifica por la cuenta bancaria origen/destino del movimiento.

## Mapeo cuenta bancaria ↔ Fuente de Financiamiento ↔ Programa

| Cuenta BancoEstado | Nombre | Programa | Uso permitido |
|---|---|---|---|
| 21909000057 | Subvención JUNJI | P02 | Solo gastos jardines |
| 21909000065 | FAEP | P02 | Solo proyectos FAEP convenidos |
| 21909000171 | Asignación Familiar | P02 | Reembolsos asig. familiar |
| 21909000260 | RESTO P01 | P01 | Gastos generales P01 (ST22, ST29) |
| 21909000278 | REMUNERACIÓN P01 | P01 | Solo personal administrativo P01 |
| 21909000324 | Lic. Médicas FONASA | P02 | Recuperaciones de licencias |
| 21909000332 | Lic. Médicas ISAPRE | P02 | Recuperaciones de licencias |
| 21909000341 | Subvención General | P02 | Subvención base + carrera docente |
| 21909000359 | PIE | P02 | Solo programa integración escolar |
| 21909000367 | SEP | P02 | Solo subvención escolar preferencial |
| 21909000375 | Subv. Mantenimiento | P02 | Solo mantenimiento infraestructura |
| 21909000383 | Pro-Retención | P02 | Subvención pro-retención |
| 21909000391 | Remuneraciones P02 | P02 | Cuenta operativa pago remuneraciones |
| 21909000405 | Inversiones ST 31 | P02 | Solo iniciativas de inversión |
| 21909000413 | Aporte Fiscal Libre P02 | P02 | Aporte fiscal complementario |
| 21909000421 | Equipamiento Téc. Prof. | P02 | Solo licitación equipamiento TP |
| 21909000430 | Liceos Bicentenarios | P02 | Solo programa liceos bicentenarios |

## Práctica operacional clave

El SLEP **centraliza el pago de remuneraciones** mediante:
1. Traspasos internos desde cada cuenta-FF hacia la cuenta 21909000391 (Remuneraciones P02)
2. Pago bancario único desde la cuenta 391 a todos los trabajadores
3. Contablemente cada FF queda imputada por su porción

Calendario mensual típico:
- **Día 18**: pago líquidos P01 (cuenta 278)
- **Fin de mes**: pago líquidos P02 + Jardines (cuenta 391)
- **Días 10-13 mes siguiente**: pago cotizaciones y aportes patronales (cuenta 391)
- **Fin de mes (~26-30)**: ingresan transferencias MINEDUC en cuentas respectivas

## Fuentes de datos del sistema

### SIGFE 2.0 (Sistema oficial contable-presupuestario)
Exporta reportes en formato `.xls` (JasperReports binario, requiere `libreoffice` headless para convertir a `.xlsx`) o nativo `.xlsx`. Hay 38 reportes distintos disponibles, agrupados en 8 categorías:

- **Tesorería**: Tesorería, Cartera Financiera Bancaria, Cartera Financiera Contable, Pago Facturas Chile Paga
- **Contabilidad**: Balance Comprobación y Saldos, Mayor Contable, Diario Contable
- **Ejecución Presupuestaria**: Estado Situación Presupuestaria, Estado Ejec. Presup. (ingresos/gastos), Estado Compromiso, Descarga Estados (Conceptos/Insumos)
- **Disponibilidades**: Disp. Devengo, Disp. Compromiso, Disp. Requerimiento
- **Mayor Presupuestario**: Mayor Req/Comp/Devengo (ingresos y gastos)
- **Diario Presupuestario**: Diario Req/Comp/Devengo
- **Cartera Presupuestaria**: Cartera Compromiso/Devengo (ingresos y gastos)
- **Transaccional**: Exportación 4 Catálogos (base maestra), Comparativo Transacciones, Etapas Compromiso, Listado Pagos/Cobros Realizados

**Validación**: todos los reportes cuadran entre sí. El saldo Banco Estado (cuenta contable 11102) = suma saldos BancoEstado al mismo corte. La integridad SIGFE es sólida.

### BancoEstado
- Saldos diarios por cuenta corriente (input manual o vía API si disponible)
- Cartolas de cuenta (cuando se requiera conciliación detallada)

### CasChile (remuneraciones)
- Maestro mensual de remuneraciones
- Se procesa con script Python propio que distribuye por FF basado en glosa/centro de costo
- Output: bruto, líquido, descuentos, aportes patronales por FF

## Ciclo presupuestario SIGFE

`Ley Vigente → Requerimiento → Compromiso → Devengo → Efectivo (pago/cobro)`

- **Ley Vigente**: presupuesto autorizado vigente (Ley inicial + modificaciones)
- **Requerimiento**: solicitud de gasto, aún no compromete recursos
- **Compromiso**: orden de compra o convenio firmado, reserva presupuestaria
- **Devengo**: factura recibida o servicio recibido, obligación contraída (genera deuda flotante hasta pagar)
- **Efectivo**: pago realizado y registrado

Una factura puede estar en cualquier estado intermedio. La diferencia Devengo - Efectivo = Deuda Flotante.

## Datos al 30/04/2026 (snapshot referencial)

- **Caja Banco Estado**: $1.650.064.705
- **Ejecución gastos vs lineal 33%**: 29,3% (alineado)
- **Ejecución ingresos**: 30,8%
- **Deuda flotante total**: $1.046.236.353 (957M personal + 83M B/S + 5M activos)
- **Pagos vencidos Chile Paga**: $15.596.892
- **Factura más atrasada**: $9.682.912 (TALLERES GRAFICOS SMIRNOW, 93 días)
- **Compromisos próximos**: $1.083.603.183
- **Caja proyectada fin mayo**: $556.288.839

## Arquitectura del sistema

```
slep_petorca_finance/
├── CLAUDE.md                    # Este archivo
├── data/
│   ├── raw/                     # Exports SIGFE/banco/CasChile sin tocar (por fecha)
│   ├── processed/               # Parquet limpios intermedios
│   └── slep.db                  # SQLite consolidada (fuente única de verdad)
├── etl/
│   ├── loaders/
│   │   ├── sigfe.py             # Loader genérico SIGFE
│   │   ├── banco.py             # Lector cartolas BancoEstado
│   │   └── caschile.py          # Lector maestro remuneraciones
│   ├── transformers.py          # Normalización, mapeo FF, validaciones
│   └── pipeline.py              # Orquestador ingest → load → validate
├── analytics/
│   ├── flujo_caja.py            # Flujo real + proyectado por FF
│   ├── disponible_ff.py         # Disponible por FF y programa
│   ├── conciliacion.py          # Cruce banco ↔ SIGFE
│   ├── salud_financiera.py      # KPIs: días caja, ratios, alertas
│   └── proyecciones.py          # Proyección caja basada en histórico
├── reports/
│   ├── dashboard.py             # Genera HTML/Excel dashboard
│   ├── informes_mensuales.py    # Informes oficiales formato DIPRES
│   └── alertas.py               # Notificaciones de eventos críticos
└── cli.py                       # CLI: slep update | dashboard | report
```

## Modelo de datos SQLite

### Tablas de hechos (transaccionales)
- `pagos` — desde Listado Pagos Realizados
- `cobros` — desde Listado Cobros Realizados
- `diario_contable` — desde Diario Contable
- `mayor_contable` — desde Mayor Contable
- `transacciones_ppto` — desde Exportación 4 Catálogos (base maestra)
- `diario_presup` — desde Diario Presupuestario (Req/Comp/Devengo unificados)
- `mayor_presup` — desde Mayor Presupuestario
- `cartera_presup_compromiso` — desde Cartera Compromiso
- `cartera_presup_devengo` — desde Cartera Devengo (incluye calendario MINEDUC histórico)
- `disponibilidad_devengo` — desde Disp Devengo
- `disponibilidad_compromiso` — desde Disp Compromiso
- `disponibilidad_requerimiento` — desde Disp Requerimiento
- `etapas_compromiso` — desde Etapas Compromiso
- `comparativo_transacciones` — desde Comparativo Transacciones
- `chile_paga_facturas` — desde Pago Facturas Chile Paga

### Tablas snapshot (cortes periódicos)
- `balance_snapshot` (mensual) — desde Balance Comprobación y Saldos
- `ejecucion_concepto` (mensual) — desde Descarga Estados Conceptos
- `ejecucion_insumos` (mensual) — desde Descarga Estados Insumos
- `situacion_presupuestaria` (mensual) — desde Estado Situación
- `estado_compromiso` (mensual) — desde Estado Compromiso
- `tesoreria_snapshot` (semanal/quincenal) — desde Tesorería
- `cartera_bancaria_snapshot` — desde Cartera Financiera Bancaria
- `cartera_contable_snapshot` — desde Cartera Financiera Contable
- `saldos_bancarios_diarios` — input manual o API

### Tablas dimensión (catálogos)
- `cuentas_bancarias` — 17 cuentas SLEP + mapeo FF + programa
- `cuentas_contables` — Plan cuentas SIGFE (clases ACTIVO/PASIVO/etc.)
- `conceptos_presupuestarios` — Catálogo ST/ítem/asig/sub-asig
- `proveedores` — RUT, nombre, métricas históricas
- `programas_presup` — P01 (Gastos Admin), P02 (Servicio Educativo)

## Convenciones

### Códigos de cuentas bancarias
Usar los últimos 3 dígitos del número de cuenta como `Cuenta_ID` corto: `057` (JUNJI), `341` (Subv. General), `391` (Remuneraciones P02), etc.

### Códigos contables
SIGFE 2.0 sigue el plan de cuentas CGR. Cuentas más usadas:
- `11102` Banco Estado (la única cuenta bancaria contable, agrupa todas las cuentas corrientes BancoEstado)
- `11403` Anticipos a Rendir Cuenta
- `11406` Anticipos Previsionales
- `11498` Deudores por Gastos Pagados en Exceso
- `21521` CxP Gastos en Personal (deuda flotante personal)
- `21522` CxP Bienes y Servicios (deuda flotante proveedores)
- `21529` CxP Adquisición Activos
- `22106` Acreedores por Transferencias Reintegrar (saldo pendiente de aclarar)

### Subtítulos presupuestarios
- `05` Transferencias Corrientes (ingreso)
- `08` Otros Ingresos Corrientes
- `09` Aporte Fiscal
- `12` Recuperación de Préstamos
- `13` Transferencias para Gastos de Capital (ingreso)
- `21` Gastos en Personal
- `22` Bienes y Servicios de Consumo
- `23` Prestaciones de Seguridad Social
- `25` Íntegros al Fisco
- `29` Adquisición de Activos No Financieros
- `31` Iniciativas de Inversión

## Flujos de uso típicos

### Flujo diario (operación):
1. Usuario actualiza saldos bancarios del día (input manual o pega del archivo)
2. Sistema carga ese día en `saldos_bancarios_diarios`
3. Dashboard se actualiza con saldos, posición, alertas

### Flujo semanal/quincenal (refresh SIGFE):
1. Usuario exporta reportes SIGFE actualizados a `data/raw/YYYY-MM-DD/`
2. Pipeline detecta archivos nuevos, los carga, valida cuadre
3. Snapshots se actualizan, vista histórica gana un punto más

### Flujo mensual (cierre):
1. Tras cierre SIGFE, se descargan Balance + Estado Situación oficial
2. Se reconcilia con saldos bancarios y maestro remuneraciones del mes
3. Se genera informe oficial mensual para Dirección Ejecutiva

## Reglas de validación

El pipeline debe validar:
1. **Saldo Banco Estado**: cuenta 11102 (SIGFE Balance) = suma cuentas BancoEstado al mismo corte
2. **Ciclo presupuestario**: Requerimiento ≥ Compromiso ≥ Devengo ≥ Efectivo (por concepto)
3. **Deuda flotante**: Devengo - Efectivo = saldo cuenta 215 (CxP Presupuestarios)
4. **Restricción FF**: pagos desde una cuenta FF deben corresponder a gastos imputables a esa FF (excepto la cuenta 391 que es operativa)

## Cosas pendientes / por resolver

1. **Cuenta 22106 "Acreedores por Transferencias Reintegrar"**: $8.299M en saldo final 30/04. Falta entender qué representa exactamente (¿saldos pendientes de años anteriores? ¿retenciones?).
2. **Maestro de remuneraciones**: integrar el output del script Python (que distribuye por FF) para imputación correcta de personal por FF.
3. **Cartolas BancoEstado**: para conciliación transaccional banco ↔ contable.
4. **Calendario MINEDUC**: explotar Cartera Devengo Ingresos para construir patrón histórico de transferencias.

## Cómo el asistente debe comportarse en este proyecto

- Es un proyecto contable-financiero del sector público. Precisión > velocidad.
- Los datos son sensibles: nunca exportar fuera del sistema sin autorización explícita.
- Cuando proponer fórmulas o queries, validar siempre que cuadre con los snapshots oficiales SIGFE (Balance, Estado Situación).
- El usuario es funcionario público trabajando en gestión financiera del SLEP. Lenguaje técnico es bienvenido (uso de "devengo", "imputación", "subtítulo", etc.).
- Para cualquier indicador o cifra que se reporte, citar la fuente SIGFE y el corte de fecha.
- Siempre que se entregue una proyección, identificar los supuestos.
