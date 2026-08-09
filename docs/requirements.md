# Requisitos

## Propósito

Diseñar una aplicación web local que ayude al fotógrafo a preparar sesiones y revisar material fotográfico sin alterar los archivos originales ni depender de modificaciones directas al catálogo de Lightroom Classic.

## Usuarios y entorno

- Usuario principal: un fotógrafo trabajando en una computadora Windows.
- Modalidad: aplicación local de un solo usuario en el MVP.
- Acceso previsto: navegador en `127.0.0.1`, sin exposición a la red por defecto.
- Persistencia prevista: SQLite local y archivos generados en un workspace configurable.

## Requisitos funcionales del MVP

### Preproducción

El sistema debe permitir representar una sesión con:

- título, fecha tentativa, estado y notas;
- estilo y objetivo visual;
- modelo mediante alias o identificador interno;
- locación;
- vestuario y variantes;
- referencias visuales mediante enlaces o copias explícitamente autorizadas;
- propuesta compartible para la modelo;
- plan interno privado del fotógrafo.

La propuesta para la modelo y el plan interno deben ser contenidos separados, con controles que eviten incluir notas internas en una exportación compartible.

### Ingesta no destructiva

Para una carpeta seleccionada, el sistema debe poder, en una fase futura de implementación:

- descubrir archivos RAW compatibles sin moverlos ni renombrarlos;
- generar o extraer miniaturas en el workspace;
- leer metadatos EXIF relevantes;
- detectar sidecars XMP y recuperar puntuaciones por estrellas;
- agrupar imágenes visualmente similares o tomadas en ráfaga;
- generar hojas de contacto derivadas;
- registrar selecciones en SQLite sin alterar la fuente.

### Integración XMP/ACR

- Leer sidecars XMP y estructuras de ajustes compatibles con ACR.
- Inventariar ajustes y máscaras sin prometer interpretación completa de todos los campos propietarios.
- Archivar cada XMP original antes de generar o aplicar una variante.
- Generar propuestas XMP en un directorio separado.
- Mantener historial, origen, fecha y checksum de cada versión.
- No modificar directamente archivos `.lrcat` en el MVP.

## Requisitos no funcionales

- Operación local y offline para las funciones principales.
- Compatibilidad prioritaria con Windows y rutas con espacios.
- Lecturas tolerantes a metadatos faltantes o archivos parcialmente incompatibles.
- Escrituras atómicas para base de datos y archivos generados cuando corresponda.
- Registro de errores sin exponer datos personales ni rutas completas por defecto.
- Recuperación: ninguna operación debe dejar como única copia una versión transformada.
- Rendimiento inicial orientado a sesiones individuales; la escala exacta queda por validar.

## Fuera del alcance del MVP

- Edición directa del catálogo Lightroom `.lrcat`.
- Revelado RAW completo o reemplazo de Lightroom/ACR.
- Modificación de píxeles en RAW originales.
- Sincronización cloud, colaboración multiusuario o acceso remoto.
- Reconocimiento facial o identificación biométrica.
- Envío automático de propuestas a modelos.
- Gestión legal completa de contratos, pagos o autorizaciones de imagen.
- Entrenamiento de modelos de IA con fotografías del usuario.

## Supuestos iniciales

- Los RAW ya están almacenados y respaldados por el fotógrafo.
- Lightroom Classic puede configurarse para leer/escribir cambios desde XMP cuando el usuario decida hacerlo.
- Un RAW puede no tener sidecar, y un sidecar puede contener campos no reconocidos.
- Las miniaturas y hojas de contacto son derivados descartables y regenerables.
- La puntuación registrada en XMP puede diferir del estado interno del catálogo si Lightroom no sincronizó metadatos.
- El sistema no necesita interpretar cada máscara de ACR para conservarla íntegramente.
- Las rutas de fotografías, catálogo, workspace y archivos privados estarán fuera del repositorio.

## Decisiones pendientes

1. Formatos RAW prioritarios y cámaras que formarán el conjunto de compatibilidad.
2. Herramienta para EXIF y extracción/render de miniaturas (por ejemplo, ExifTool y/o una biblioteca RAW).
3. Criterio de similitud: cercanía temporal, hash perceptual, embeddings locales o combinación.
4. Tamaño máximo típico de una sesión y tiempo de procesamiento aceptable.
5. Taxonomía de estados y campos obligatorios de preproducción.
6. Formato de la propuesta compartible: HTML local, PDF o ambos.
7. Política final para aplicar propuestas XMP junto a los RAW y confirmaciones requeridas.
8. Alcance de lectura de máscaras ACR y versiones de proceso que deben validarse.
9. Política de copias de seguridad, retención y eliminación del workspace.
10. Qué información personal de modelos, si alguna, puede almacenarse en SQLite.

## Criterios de aceptación del diseño previo a implementación

- Las rutas y fronteras de escritura están definidas y son verificables.
- Existe una política acordada de versionado y restauración XMP.
- Los datos privados se separan del contenido compartible y del repositorio.
- El flujo de selección puede funcionar sin modificar RAW ni `.lrcat`.
- Las decisiones pendientes críticas tienen responsable y resolución documentada.
