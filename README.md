# SLEP Petorca — Sistema de Gestión Financiera

Sistema asistente contable-presupuestario que integra **SIGFE 2.0**, **BancoEstado** y **CasChile** (remuneraciones) en una base de datos local con dashboard tiempo real, alertas, conciliación bancaria-contable y proyecciones de flujo de caja.

Ver [CLAUDE.md](CLAUDE.md) para el contexto institucional completo, especificación funcional y reglas de negocio.

> ⚠️ **Importante sobre privacidad**: este repositorio contiene **solo código**. Los datos (reportes SIGFE, saldos bancarios, maestros de remuneraciones) NUNCA se versionan ni suben a GitHub. Ver [`.gitignore`](.gitignore).

## Stack

- Python 3.11+
- SQLite (base de datos local)
- LibreOffice headless (conversión .xls Jasper → .xlsx)
- openpyxl, pandas

## Setup inicial

### 1. Clonar el repositorio

```bash
git clone https://github.com/<tu-usuario>/slep_petorca_finance.git
cd slep_petorca_finance
```

### 2. Instalar LibreOffice (para convertir reportes SIGFE)

```bash
# macOS
brew install --cask libreoffice

# Ubuntu/Debian
sudo apt update && sudo apt install libreoffice

# Verificar
libreoffice --version
```

### 3. Crear entorno virtual e instalar dependencias

```bash
python3 -m venv venv
source venv/bin/activate         # Linux/macOS
# venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

### 4. Copiar reportes SIGFE

Los reportes se descargan desde SIGFE 2.0 y se organizan por fecha de corte:

```bash
mkdir -p data/raw/2026-04-30
mv ~/Downloads/SB_*.xls       data/raw/2026-04-30/
mv ~/Downloads/Estado_*.xlsx  data/raw/2026-04-30/
mv ~/Downloads/Tesorerí*.xlsx data/raw/2026-04-30/
mv ~/Downloads/Pago_de_*.xlsx data/raw/2026-04-30/
mv ~/Downloads/Cartera_*.xlsx data/raw/2026-04-30/
mv ~/Downloads/Diario_*.xlsx  data/raw/2026-04-30/
```

### 5. Ingestar a SQLite

```bash
python -m etl.pipeline --raw data/raw/2026-04-30 --fecha-corte 2026-04-30
```

Debería procesar ~45 archivos en menos de un minuto y crear `data/slep.db`.

### 6. Verificar

```bash
sqlite3 data/slep.db ".tables"
sqlite3 data/slep.db "SELECT COUNT(*) FROM pagos"
sqlite3 data/slep.db "SELECT * FROM cuentas_bancarias"
```

## Uso con Claude Code

Este proyecto está optimizado para trabajar con **Claude Code**. El archivo [`CLAUDE.md`](CLAUDE.md) contiene todo el contexto institucional para que Claude entienda el negocio sin re-explicaciones:

```bash
cd slep_petorca_finance
claude
```

Sugerencias para los primeros prompts:
- "Lee CLAUDE.md y dime qué entiendes del proyecto"
- "Ejecuta el pipeline con los datos de data/raw/2026-04-30 y dame el estado actual"
- "Construye analytics/conciliacion.py para cruzar saldos banco ↔ SIGFE 11102"

## Estructura

```
slep_petorca_finance/
├── CLAUDE.md              # Contexto institucional + reglas
├── README.md              # Este archivo
├── requirements.txt       # Dependencias Python
├── .gitignore             # Datos sensibles NO versionados
├── data/
│   ├── raw/               # Reportes SIGFE (NO versionados)
│   ├── processed/         # Cache parquet (NO versionado)
│   └── slep.db            # SQLite (NO versionada)
├── etl/
│   ├── loaders/
│   │   └── sigfe.py       # ✅ Loader genérico SIGFE
│   └── pipeline.py        # ✅ Pipeline ingesta a SQLite
├── analytics/             # ⏳ Por construir
├── reports/               # ⏳ Por construir
└── docs/                  # Documentación adicional
```

## Estado actual

✅ Loader SIGFE robusto (probado con 27 tipos de reporte)
✅ Pipeline de ingesta a SQLite (~26.000 registros en 29 tablas)
✅ Catálogo de cuentas bancarias precargado (17 cuentas SLEP Petorca)
✅ Validaciones de cuadre confirmadas (Balance ↔ Estado Situación ↔ Bancos)

⏳ Pendiente:
- `analytics/conciliacion.py` — cruce banco ↔ SIGFE
- `analytics/disponible_ff.py` — disponible por Fuente de Financiamiento
- `analytics/flujo_caja.py` — flujo de caja proyectado
- `reports/dashboard.py` — dashboard HTML tiempo real
- `reports/alertas.py` — motor de alertas
- Integración maestro remuneraciones CasChile

## Contribución

Este repositorio es privado del SLEP Petorca. Para sugerencias o mejoras al código, abrir issue o pull request.

## Licencia

Uso interno SLEP Petorca. No distribuir.
