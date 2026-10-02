# Pirineos · lámina de relieve

Proyecto propio para una lámina horizontal de **150 × 60 cm**, inspirado en la estética de los atlas clásicos. Las elevaciones, ríos, lagos, carreteras y poblaciones proceden de datos geográficos reales. No se utiliza generación de imágenes con IA.

## Archivos de impresión

El proceso genera en `output/`:

- `pirineos-150x60cm.pdf`: página de 1500 × 600 mm, relieve rasterizado y texto/geometrías vectoriales, fuentes incrustadas.
- `pirineos-150x60cm.png`: imagen con resolución física registrada; a 200 ppp mide aproximadamente 11811 × 4724 píxeles.
- `vista-previa.jpg`: vista previa ligera.
- `manifest.json`: ámbito, proyección, fuentes, fecha de datos OSM, elevaciones, etiquetas y sumas SHA-256.
- `osm-snapshot.json`: instantánea OpenStreetMap para reproducir y auditar las capas, sujeta a ODbL.

En la imprenta: tamaño final **150 × 60 cm**, escala 100 %, sin ajustar ni recortar, papel mate de calidad. Los márgenes crema ya forman parte del diseño. El PDF se entrega en RGB; pedir a la imprenta la conversión con el perfil del papel antes de imprimir. No incluye sangrado porque está diseñado con margen interior.

## Reproducción

Requiere Python 3.11 o posterior. Desde esta carpeta:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python build.py --dpi 200 --zoom 12
```

La primera ejecución descarga las teselas de elevación y una instantánea de OpenStreetMap. Se conservan en `cache/` para evitar solicitudes repetidas. Para una nueva fecha OSM, borrar únicamente `cache/osm.json`. Las fuentes externas deben estar disponibles: el proceso falla si una capa está incompleta, en lugar de sustituirla por datos inventados.

Para una prueba más rápida: `python build.py --dpi 100 --zoom 10`. Para una exportación más grande: `--dpi 300`; exige más memoria y no añade precisión geográfica a los datos originales.

El flujo `pirineos-lamina.yml` genera la versión de impresión a 200 ppp y publica los archivos en la misma rama que lo ejecutó. También proporciona un ZIP como artefacto de GitHub Actions. Los archivos superiores a 95 MB se conservan solo en ese ZIP para respetar el límite de GitHub.

## Diseño y ámbito

Cubre la cordillera del Atlántico al Mediterráneo, con Jaca destacada. Proyección ETRS89 / UTM 31N (EPSG:25831). Paleta hipsométrica discreta y sombreado con iluminación de varias direcciones calculado a partir de las elevaciones reales. Curvas de nivel cada 500 m, hidrografía azul grisácea y carreteras principales finas.

Se rotula una selección de cumbres y poblaciones de OpenStreetMap; sus coordenadas y altitudes vienen de esa fuente. Las posiciones regionales de las etiquetas de valles se documentan en `valleys.json`: son ubicaciones tipográficas aproximadas, no límites de cuencas. La colocación mide las cajas de texto para reducir solapamientos.

## Fuentes, atribución y derechos

- **Relieve:** [Terrain Tiles / Mapzen](https://registry.opendata.aws/terrain-tiles/), servido por AWS Open Data. Incluye SRTM y otras fuentes. [Fuentes y condiciones](https://github.com/tilezen/joerd/blob/master/docs/attribution.md). La resolución nativa y la calidad dependen de la fuente; el tamaño en píxeles del archivo de impresión no implica una precisión de 30 m en todo el ámbito.
- **Ríos, lagos, carreteras, poblaciones y cumbres:** © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Se obtiene mediante Overpass. La instantánea publicada mantiene esa licencia.
- **Valles:** selección editorial y coordenadas regionales en `valleys.json`.
- **Tipografía:** DejaVu Serif, instalada con Matplotlib y embebida en el PDF bajo sus condiciones.
- **Referencia visual:** [Tresmiles del Pirineo](https://rforcano.github.io/tresmiles-pirineo/). Este proyecto no copia su código ni depende de su repositorio.

El código propio tiene licencia MIT, en `LICENSE`. Esa licencia no sustituye las condiciones de los datos ni de las fuentes. Lámina decorativa; no es una carta para navegación de montaña.
