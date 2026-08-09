# Diseño inicial

## Enfoque

La aplicación futura se organizará como un sistema local con límites estrictos entre fuentes fotográficas, datos privados y artefactos generados. Flask expondrá una interfaz local; SQLite almacenará estructura y decisiones; los procesadores de archivos operarán mediante rutas configuradas.

## Componentes conceptuales

### Interfaz web local

Pantallas previstas para sesiones, preproducción, exploración de carpetas, grupos similares, hojas de contacto, selecciones e historial XMP. Usará HTML, CSS y JavaScript vanilla.

### Servicio de aplicación

Coordinará casos de uso y permisos de escritura. No deberá contener lógica específica de formatos RAW o XMP en las rutas HTTP.

### Dominio

Conceptos iniciales:

- `Session`: sesión fotográfica y estado de producción.
- `ModelProfile`: referencia mediante alias e identificador, sin requerir datos legales.
- `Location`, `WardrobeItem`, `Reference` y `ShotPlan`.
- `PhotoAsset`: referencia inmutable a un archivo fuente y su huella.
- `MetadataSnapshot`: EXIF/XMP observado en un momento dado.
- `SimilarityGroup`: agrupación calculada y editable.
- `Selection`: decisión del fotógrafo con estado y notas.
- `XmpVersion`: snapshot o propuesta versionada con checksum y procedencia.

### Adaptadores de archivos

- Descubrimiento de RAW en modo solo lectura.
- Extracción de miniaturas y EXIF.
- Parser/serializador XMP que preserve nodos desconocidos.
- Generador de hojas de contacto.
- Adaptador futuro para aplicar sidecars con validaciones explícitas.

### Persistencia

SQLite almacenará registros, referencias a rutas y resultados de análisis. Los binarios derivados y snapshots XMP vivirán en el workspace; la base guardará sus ubicaciones relativas, checksums y metadatos.

## Fronteras de almacenamiento

```text
Repositorio de código
  documentación, código futuro, pruebas sintéticas

Fuentes externas (solo lectura)
  RAW, JPG originales, XMP existentes, catálogo .lrcat

Workspace generado (lectura/escritura)
  SQLite, miniaturas, hojas de contacto, snapshots y propuestas XMP

Área privada externa
  información sensible y archivos privados de modelos
```

No se usarán rutas relativas al repositorio para encontrar material real. La configuración local debe nombrar explícitamente las raíces permitidas.

## Principios de diseño

- **No destructivo:** leer las fuentes y escribir derivados en otro lugar.
- **Trazabilidad:** registrar checksum, timestamp, herramienta y archivo origen.
- **Preservación:** al transformar XML, conservar campos y namespaces desconocidos.
- **Idempotencia:** volver a analizar una fuente sin cambios no debe duplicar activos ni versiones.
- **Mínimo privilegio:** una operación de análisis no recibe capacidad de escribir en la carpeta RAW.
- **Portabilidad:** normalizar rutas para comparación, sin perder su representación válida en Windows.

## Flujo de datos resumido

1. El usuario registra una sesión y su plan.
2. Vincula una carpeta fuente externa.
3. El sistema inventaría archivos y calcula huellas sin modificar la carpeta.
4. Los adaptadores extraen miniaturas y metadatos al workspace.
5. El sistema propone grupos y genera vistas derivadas.
6. El usuario registra selecciones en SQLite.
7. Si corresponde, el sistema crea propuestas XMP separadas.
8. Una operación futura, explícita y confirmada podrá aplicar propuestas, siempre con snapshot previo.

## Seguridad y fallos

- Validar que una ruta de salida no esté dentro de una raíz fuente.
- Evitar seguir enlaces o junctions que escapen de las raíces autorizadas hasta definir una política.
- Usar archivos temporales y reemplazo atómico para artefactos generados.
- Marcar archivos cambiados desde el último análisis mediante tamaño, fecha y checksum.
- Ante XML inválido, conservar el archivo intacto, registrar el error y omitir la propuesta.

## Diseño aún no decidido

- Esquema físico de SQLite y estrategia de migraciones.
- Librerías concretas y distribución para Windows.
- Estrategia exacta de colas o procesamiento en segundo plano.
- Algoritmo y representación de similitud.
- Contrato entre parser XMP y generador de propuestas.
- Mecanismo de previsualización/diff de cambios XMP.
