# Diseño inicial

## Enfoque

La aplicación futura se organizará como un sistema local con límites estrictos entre fuentes fotográficas, datos privados y artefactos generados. Flask expondrá una interfaz local; SQLite almacenará estructura y decisiones; los procesadores de archivos operarán mediante rutas configuradas.

La Fase 0 implementará sólo el recorrido de posproducción en lectura. Lightroom Classic seguirá siendo el editor principal y no habrá componentes capaces de escribir sobre fuentes, sidecars o catálogos.

## Componentes conceptuales

### Interfaz web local

En la Fase 0 se prevén pantallas para vincular una sesión, revisar el inventario, filtrar por estrellas, generar proxies, ver una hoja de contacto, confirmar una selección reducida, preparar un paquete local de revisión y registrar manualmente recomendaciones. Las pantallas de preproducción, propuestas creativas e historial editable XMP quedan para fases futuras.

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

Para la Fase 0 se requieren además:

- `SessionInventory`: inventario de hasta 200 fotografías y archivos auxiliares.
- `AssetRelation`: relación por nombre base entre NEF, XMP, ACR y JPG.
- `PreviewAsset`: derivado con fuente explícita (`lightroom_export` o `nef_approximation`).
- `ProxyAsset`: JPG sRGB privado, regenerable y sin metadatos sensibles innecesarios.
- `UserConfirmedSelection`: selección reducida confirmada por el usuario.
- `ReviewPackage`: hoja de contacto, proxies seleccionados y manifiesto JSON minimizado para descarga manual.
- `ReviewRecommendation`: recomendación incorporada manualmente y nunca aplicada por la aplicación.

### Adaptadores de archivos

- Descubrimiento de RAW en modo solo lectura.
- Extracción de miniaturas y EXIF.
- Parser/serializador XMP que preserve nodos desconocidos.
- Generador de hojas de contacto.
- Adaptador futuro para aplicar sidecars con validaciones explícitas.

Los adaptadores activos de la Fase 0 serán de lectura para fuentes. El generador de proxies y hojas de contacto sólo podrá escribir dentro del workspace privado. El adaptador de escritura de sidecars no formará parte de la primera implementación.

### Persistencia

SQLite almacenará registros, referencias a rutas y resultados de análisis. Los binarios derivados y snapshots XMP vivirán en el workspace; la base guardará sus ubicaciones relativas, checksums y metadatos.

## Fronteras de almacenamiento

```text
Repositorio de código
  documentación, código futuro, pruebas sintéticas

Fuentes externas (solo lectura)
  RAW, JPG originales, XMP existentes, catálogo .lrcat

Workspace generado (lectura/escritura)
  SQLite, proxies, miniaturas y hojas de contacto

Área privada externa
  información sensible y archivos privados de modelos
```

No se usarán rutas relativas al repositorio para encontrar material real. La configuración local debe nombrar explícitamente las raíces permitidas.

Los snapshots y propuestas XMP corresponden a fases futuras y no se generarán en la Fase 0.

## Principios de diseño

- **No destructivo:** leer las fuentes y escribir derivados en otro lugar.
- **Trazabilidad:** registrar checksum, timestamp, herramienta y archivo origen.
- **Preservación:** al transformar XML, conservar campos y namespaces desconocidos.
- **Idempotencia:** volver a analizar una fuente sin cambios no debe duplicar activos ni versiones.
- **Mínimo privilegio:** una operación de análisis no recibe capacidad de escribir en la carpeta RAW.
- **Portabilidad:** normalizar rutas para comparación, sin perder su representación válida en Windows.
- **Procedencia visual:** cada preview declara si proviene de una exportación Lightroom o de una aproximación obtenida desde NEF.
- **Control humano:** ninguna sugerencia cambia una selección ni se convierte en ajuste sin confirmación del usuario.
- **Handoff explícito:** la aplicación termina su responsabilidad al generar y permitir descargar el paquete local; el usuario controla cualquier carga externa.

## Flujo de datos resumido

1. El usuario guarda metadatos en Lightroom Classic con `Ctrl+S` y vincula una carpeta externa.
2. El sistema inventaría NEF, JPG, XMP y ACR sin modificar la carpeta.
3. Relaciona archivos por nombre base y lee EXIF y estrellas desde XMP.
4. Filtra por estrellas y genera proxies en el workspace.
5. Genera una hoja de contacto para revisión general.
6. El usuario confirma una selección reducida de aproximadamente 12 a 30 fotografías.
7. La aplicación prepara únicamente la selección confirmada para análisis visual asistido mediante un paquete local.
8. El usuario decide si descarga y comparte manualmente el paquete con ChatGPT.
9. El análisis conversacional ocurre fuera de la aplicación y sin integración mediante API.
10. El usuario registra manualmente las recomendaciones y su estado, sin aplicarlas.

## Seguridad y fallos

- Validar que una ruta de salida no esté dentro de una raíz fuente.
- Evitar seguir enlaces o junctions que escapen de las raíces autorizadas hasta definir una política.
- Usar archivos temporales y reemplazo atómico para artefactos generados.
- Marcar archivos cambiados desde el último análisis mediante tamaño, fecha y checksum.
- Ante XML inválido, conservar el archivo intacto, registrar el error y omitir la propuesta.
- No instanciar componentes de escritura sobre XMP o fuentes en la Fase 0.
- Bloquear cualquier ruta de salida situada dentro de la sesión fuente o del repositorio.
- No asumir equivalencia visual entre un JPG exportado por Lightroom y un preview aproximado desde NEF.
- No incluir clientes HTTP, credenciales ni automatismos de carga para ChatGPT u otros servicios externos.

## Diseño aún no decidido

- Esquema físico de SQLite y estrategia de migraciones.
- Librerías concretas y distribución para Windows.
- Estrategia exacta de colas o procesamiento en segundo plano.
- Algoritmo y representación de similitud.
- Contrato entre parser XMP y generador de propuestas.
- Mecanismo de previsualización/diff de cambios XMP.
- Estrategia futura de escritura y recuperación XMP/ACR.
- Política de retención y limpieza manual de derivados.
- Implementación y evaluación de las sugerencias visuales.
- Análisis visual local, integración futura mediante API e importación estructurada de resultados.
