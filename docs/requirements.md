# Requisitos

## Propósito

Diseñar una aplicación web local que ayude al fotógrafo a preparar sesiones y revisar material fotográfico sin alterar los archivos originales ni depender de modificaciones directas al catálogo de Lightroom Classic.

La visión completa incluye preproducción, propuesta creativa y posproducción. El alcance activo es únicamente la Fase 0 de posproducción descrita en `phase-0-postproduction.md`.

## Usuarios y entorno

- Usuario principal: un fotógrafo trabajando en una computadora Windows.
- Modalidad: aplicación local de un solo usuario en el MVP.
- Acceso previsto: navegador en `127.0.0.1`, sin exposición a la red por defecto.
- Persistencia prevista: SQLite local y archivos generados en un workspace configurable.

## Requisitos funcionales de la Fase 0

### Entrada y compatibilidad

- Trabajar con material ya seleccionado y editado parcialmente en Lightroom Classic.
- Soportar inicialmente Nikon NEF de una Nikon D7000, JPG, sidecars XMP y archivos ACR auxiliares encontrados en la sesión.
- Inventariar hasta 200 fotografías por sesión.
- Relacionar NEF, XMP, ACR y JPG mediante nombre base sin mover ni renombrar archivos.
- Leer EXIF y estrellas desde XMP; el usuario debe guardar previamente los metadatos desde Lightroom con `Ctrl+S`, y las estrellas representan únicamente ese último estado guardado en el sidecar.
- Tratar XMP como única fuente accesible de estrellas y advertir que puede no coincidir con el catálogo.

### Reducción y preparación para revisión

- Filtrar el inventario por estrellas leídas desde XMP.
- Generar proxies JPG sRGB, con lado largo configurable —2048 px por defecto— y calidad aproximada de 85.
- Omitir metadatos sensibles innecesarios en los proxies.
- Guardar proxies y hojas de contacto únicamente en el workspace privado externo al repositorio.
- Aceptar como preview un JPG exportado por Lightroom o una previsualización extraída/revelada desde NEF.
- Identificar claramente la procedencia del preview y no presentar ambas fuentes como visualmente equivalentes.
- Generar una hoja de contacto para la revisión general.
- Permitir al usuario confirmar una selección reducida, con objetivo aproximado de 12 a 30 fotografías.
- Preparar únicamente la selección confirmada para análisis visual asistido mediante un paquete local de revisión.

### Paquete de revisión y handoff manual

- Generar un paquete local con hoja de contacto, proxies correspondientes únicamente a la selección confirmada y un manifiesto JSON.
- Excluir del manifiesto rutas absolutas, GPS y datos personales.
- Incluir procedencia de cada preview, rating leído desde XMP, datos técnicos mínimos e identificador o nombre de archivo para volver a Lightroom.
- Permitir revisar y descargar el paquete para una carga manual y explícita decidida por el usuario.
- No enviar automáticamente fotografías, proxies, XMP ni metadatos a ChatGPT ni a ningún servicio externo.
- No controlar ChatGPT, utilizar su API ni almacenar credenciales.
- Distinguir preparación local, carga manual, análisis conversacional externo y registro manual de recomendaciones.

Las sugerencias de exposición, color, coherencia, similitud, posibles seleccionadas, ajustes globales y máscaras se producirán durante la revisión asistida externa. La aplicación no las calculará internamente en la Fase 0 y nunca las aplicará automáticamente.

### Restricciones obligatorias

- No modificar XMP, ACR, NEF, JPG, TIFF ni DNG.
- No abrir ni escribir catálogos `.lrcat`.
- No crear ni restaurar versiones XMP/ACR.
- No eliminar archivos.
- Mantener Lightroom Classic como herramienta principal de edición.
- Limitar toda salida compartible a una acción manual y explícita del usuario.

## Requisitos funcionales futuros, fuera de la Fase 0

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

### Ingesta y posproducción ampliadas

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

Estos requisitos describen la dirección futura y no autorizan escritura XMP durante la Fase 0.

## Requisitos no funcionales

- Operación local y offline para las funciones principales.
- Compatibilidad prioritaria con Windows y rutas con espacios.
- Lecturas tolerantes a metadatos faltantes o archivos parcialmente incompatibles.
- Escrituras atómicas para base de datos y archivos generados cuando corresponda.
- Registro de errores sin exponer datos personales ni rutas completas por defecto.
- Recuperación: ninguna operación debe dejar como única copia una versión transformada.
- Rendimiento inicial orientado a sesiones individuales; la escala exacta queda por validar.
- Capacidad objetivo de la Fase 0: hasta 200 fotografías, con revisión general mediante proxies y paquete de análisis asistido limitado a 12 a 30 fotografías confirmadas.

## Fuera del alcance del MVP

- Edición directa del catálogo Lightroom `.lrcat`.
- Revelado RAW completo o reemplazo de Lightroom/ACR.
- Modificación de píxeles en RAW originales.
- Sincronización cloud, colaboración multiusuario o acceso remoto.
- Reconocimiento facial o identificación biométrica.
- Envío automático de propuestas a modelos.
- Gestión legal completa de contratos, pagos o autorizaciones de imagen.
- Entrenamiento de modelos de IA con fotografías del usuario.
- Escritura, aplicación o recuperación de XMP/ACR.
- Agrupación automática avanzada.
- Preproducción, propuesta creativa, planificación y presentación para la modelo.

## Supuestos iniciales

- Los RAW ya están almacenados y respaldados por el fotógrafo.
- Lightroom Classic puede configurarse para leer/escribir cambios desde XMP cuando el usuario decida hacerlo.
- Un RAW puede no tener sidecar, y un sidecar puede contener campos no reconocidos.
- Las miniaturas y hojas de contacto son derivados descartables y regenerables.
- Los proxies son derivados privados y regenerables, no representaciones necesariamente equivalentes a la edición de Lightroom.
- La puntuación registrada en XMP puede diferir del estado interno del catálogo si Lightroom no sincronizó metadatos.
- El sistema no necesita interpretar cada máscara de ACR para conservarla íntegramente.
- Las rutas de fotografías, catálogo, workspace y archivos privados estarán fuera del repositorio.

## Decisiones futuras que no bloquean la Fase 0

1. Formatos RAW prioritarios y cámaras que formarán el conjunto de compatibilidad.
2. Herramienta concreta para EXIF y extracción/render de previews NEF.
3. Criterio de similitud: cercanía temporal, hash perceptual, embeddings locales o combinación.
4. Objetivos de tiempo de procesamiento y límite de almacenamiento del workspace.
5. Taxonomía de estados y campos obligatorios de preproducción.
6. Formato de la propuesta compartible: HTML local, PDF o ambos.
7. Política futura para aplicar y recuperar propuestas XMP junto a los RAW.
8. Alcance de lectura de máscaras ACR y versiones de proceso que deben validarse.
9. Política de copias de seguridad, retención y eliminación del workspace.
10. Qué información personal de modelos, si alguna, puede almacenarse en SQLite.
11. Reglas exactas para elegir entre un JPG exportado por Lightroom y un preview aproximado de NEF.
12. Posible análisis visual local, integración mediante API e importación estructurada de resultados.
13. Umbrales y presentación de advertencias de exposición, color, similitud y coherencia.
14. Política de retención y limpieza manual de proxies y hojas de contacto.

## Criterios de aceptación del diseño previo a implementación

- Las rutas y fronteras de escritura están definidas y son verificables.
- El versionado y la restauración XMP permanecen explícitamente fuera de la Fase 0 y documentados como trabajo futuro.
- Los datos privados se separan del contenido compartible y del repositorio.
- El flujo de selección puede funcionar sin modificar RAW ni `.lrcat`.
- Las decisiones pendientes críticas tienen responsable y resolución documentada.
- Cada preview identifica su fuente y el usuario confirma la selección antes de la preparación del paquete de revisión.
