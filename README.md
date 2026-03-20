# eltabasqueño.com (ajentedeventas)

Sitio web estático para mostrar un catálogo de autos por marca a partir de fuentes públicas.

Actualmente:

- Toyota Tabasco: scraper con Playwright (contenido dinámico)
- Nissan Deportiva: scraper con Requests/BeautifulSoup (HTML + sección de “Versiones”)

El sitio **no consulta** directamente a Toyota/Nissan al navegar. Solo consume archivos JSON locales generados por los scrapers.

## Requisitos del sistema

- macOS
- Python 3.13 (recomendado) o Python 3.12
- `pip`
- Conexión a internet (solo para ejecutar scrapers)

### Dependencias Python

Instalación desde `requirements.txt`.

- `requests`
- `beautifulsoup4`
- `lxml`
- `playwright`

### Playwright (Chromium)

Toyota Tabasco requiere renderizado con navegador headless.

Debes instalar Chromium una sola vez:

```bash
python -m playwright install chromium
```

## Estructura del proyecto

- `index.html`: UI del catálogo
- `styles.css`: estilos
- `data/catalog.json`: catálogo Toyota (generado)
- `data/nissan.json`: catálogo Nissan (generado)
- `scripts/scrape_toyota_tabasco.py`: scraper Toyota (Playwright)
- `scripts/scrape_nissan_deportiva.py`: scraper Nissan (Requests/BS4)

## Configuración inicial

Crear y activar entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Instalar dependencias:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Generar catálogos

### Toyota

Genera `data/catalog.json`:

```bash
python scripts/scrape_toyota_tabasco.py --out data/catalog.json --limit 50
```

Notas:

- El scraper hace peticiones a `toyotatabasco.com.mx` **solo cuando se ejecuta**.
- Al navegar el sitio web, no se hacen peticiones a Toyota.

### Nissan

Genera `data/nissan.json`:

```bash
python scripts/scrape_nissan_deportiva.py --out data/nissan.json --limit 50
```

Notas:

- El scraper toma precios desde la sección “Versiones” (valores “Desde: $ ...”).
- Al navegar el sitio web, no se hacen peticiones a Nissan.

## Ejecutar el sitio

Puedes servir el sitio con cualquier servidor estático.

Ejemplos:

- Python:

```bash
python -m http.server 2200
```

Luego abre:

- `http://localhost:2200/`

## Uso

1. Abre el sitio.
2. Selecciona una marca en el selector.
3. El sitio carga el JSON correspondiente:
   - Toyota → `data/catalog.json`
   - Nissan → `data/nissan.json`

## Actualización diaria (5:00 AM)

Los scrapers están pensados para ejecutarse en un schedule externo.

Ejemplo (conceptual):

- 05:00 AM: ejecutar scrapers Toyota y Nissan
- Actualizar los JSON en `data/`

(La automatización exacta puede hacerse con `cron` o con GitHub Actions.)
# agentedeventas
