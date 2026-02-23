🚀
# 🟥 The Matrix Lab

> Panel de análisis técnico en tiempo real · Gráfico 4H · Niveles fractales · Vigilancia de activos

---

## ¿Qué es?

**The Matrix Lab** es una aplicación web de análisis técnico construida con FastAPI y Plotly. Permite visualizar gráficos de velas en temporalidad de **4 horas** para más de 30 activos financieros (índices, forex, materias primas, cripto y ETFs), con indicadores clave, niveles fractales automáticos y un sistema de alertas en tiempo real.

---

## Características principales

### 📊 Gráfico 4H interactivo
- Velas OHLC con área de precio superpuesta
- **EMA 200** (azul) y **EMA 800** (verde) configuradas por activo
- Niveles fractales menores (amarillo) y mayores (negro) generados automáticamente
- Zonas sombreadas alrededor de los niveles mayores
- Líneas de apertura del **año** y la **semana** actual
- Marcadores de RSI extremo (<30 / >70) sobre el precio
- Panel RSI 14 sincronizado con el zoom del gráfico principal
- Smart Y-axis: el eje vertical se auto-escala a las velas visibles

### ⬡ Niveles fractales
Cada activo tiene su propia configuración de espaciado fractal (`key_spacing`, `major_spacing`, `zone_size`) calibrada según su precio y volatilidad habitual. Los niveles se calculan dinámicamente alrededor del precio actual.

### 🔔 Sistema de vigilancia
- Marca cualquier activo con ★ para añadirlo a vigilancia
- Revisión automática cada 5 minutos
- Alertas cuando el precio **cruza** o **toca** las EMAs
- Detección de **Golden Cross** y **Death Cross**
- Historial de alertas de los últimos 7 días con timestamp
- Toasts en tiempo real en pantalla

### 📋 Tabla de activos
- Vista completa de todos los activos con precio, cambio %, RSI, posición respecto a las EMAs y estado del cruce
- Sparkline del último mes por activo
- Badge de estado (Favorable / Interesante / Considerar / No ahora) basado en RSI y distancia a las EMAs
- Clic en cualquier fila carga el gráfico

---

## Activos disponibles

| Categoría | Tickers |
|---|---|
| Índices | ^DJI, ^NDX, ^GSPC, ^RUT |
| Futuros | YM=F, NQ=F, GC=F, SI=F, CL=F |
| Forex | USDJPY=X, GBPJPY=X, EURUSD=X, AUDUSD=X |
| Bonos / Dólar | ^TNX, ^TYX, DX=F |
| Cripto | BTC-USD, ETH-USD |
| ETFs | SPY, VOO, VTI, QQQ, QQQM, GLD, IAU, GDX, IWM, SMH, XLE, SCHD, SCHG, VGT, EEM, DIA, AAPL y más |

Cualquier símbolo de Yahoo Finance puede buscarse manualmente desde el input del header.

---

## Tecnología

```
Backend   FastAPI + yfinance + pandas + numpy
Frontend  HTML / CSS / JS vanilla + Plotly.js 2.27
Servidor  Uvicorn
Fuentes   Syne + Space Mono (Google Fonts)
```

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/matrix-lab.git
cd matrix-lab

# 2. Instalar dependencias
pip install fastapi uvicorn yfinance pandas numpy

# 3. Estructura esperada
matrix-lab/
├── main.py
├── templates/
│   └── index.html
└── static/
    └── logo.png

# 4. Ejecutar
python main.py
# o directamente con uvicorn:
uvicorn main:app --reload --port 8000
```

Abre `http://localhost:8000` en tu navegador.

---

## API endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Interfaz principal |
| `GET` | `/api/chart/{ticker}` | Velas 4H + EMAs + RSI + fractales + alertas |
| `GET` | `/api/row/{ticker}` | Datos resumidos para la tabla |
| `GET` | `/api/sparkline/{ticker}` | Cierre diario del último mes |
| `GET` | `/api/watch?tickers=A,B` | Alertas de la watchlist |

---

## Configuración de activos

Cada activo en `ASSET_CONFIG` (dentro de `main.py`) define:

```python
"GC=F": {
    "key_spacing":   50,    # distancia entre niveles fractales menores
    "major_spacing": 100,   # distancia entre niveles fractales mayores
    "zone_size":     10,    # semiancho de la zona sombreada
    "ema_short":     200,   # periodo EMA corta
    "ema_long":      800,   # periodo EMA larga
}
```

Para activos no definidos, se aplica una heurística automática basada en el precio actual.

---

## Lógica de alertas

| Condición | Tipo |
|---|---|
| Precio cruza EMA al alza | 🟢 bullish |
| Precio cruza EMA a la baja | 🔴 bearish |
| Precio dentro del 0.4% de una EMA | 🔵 info |
| EMA corta cruza EMA larga al alza | 🟢 Golden Cross |
| EMA corta cruza EMA larga a la baja | 🔴 Death Cross |

---

## Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `PORT` | `8000` | Puerto del servidor |

```bash
PORT=3000 python main.py
```

---

## Despliegue

El proyecto está preparado para desplegarse en cualquier plataforma que soporte Python:

```bash
# Railway / Render / Fly.io
# Start command:
uvicorn main:app --host 0.0.0.0 --port $PORT
```

---

## Licencia

MIT — libre para uso personal y comercial.

