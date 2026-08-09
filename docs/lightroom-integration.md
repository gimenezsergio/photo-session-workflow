# Integración con Lightroom Classic y ACR

## Alcance

El MVP se integrará mediante archivos XMP y convenciones compatibles con Adobe Camera Raw. El catálogo `.lrcat` se considera una fuente fuera de límites: podrá registrarse su ubicación como referencia, pero no se abrirá para escritura ni se modificará directamente.

## Modelo de interacción

### Lectura

- Detectar el sidecar asociado a cada RAW según su nombre y ubicación.
- Leer XML con namespaces XMP/RDF y campos ACR conocidos.
- Recuperar la puntuación por estrellas cuando esté presente.
- Inventariar ajustes de revelado y presencia de estructuras de máscaras.
- Conservar campos desconocidos sin interpretarlos ni descartarlos.

### Propuesta

- Partir de una copia byte a byte del sidecar vigente cuando exista.
- Registrar checksum, tamaño y fecha del archivo base.
- Aplicar únicamente transformaciones explícitas sobre la copia.
- Guardar la salida en un directorio de propuestas con un manifiesto de procedencia.
- Validar que el resultado sea XML bien formado antes de ofrecer su aplicación.

### Aplicación futura

La escritura junto al RAW estará deshabilitada por defecto. Si se incorpora al MVP deberá:

- requerir confirmación explícita;
- detectar conflictos comparando el sidecar vigente con el checksum base;
- archivar la versión vigente antes de escribir;
- usar una escritura temporal y reemplazo atómico;
- permitir restauración y registrar cada resultado;
- abstenerse de escribir si el archivo cambió o la compatibilidad es incierta.

## Versionado de sidecars

Cada versión archivada o propuesta debería registrar:

- identificador del activo y ruta fuente;
- checksum del RAW usado para asociación;
- checksum y timestamp del XMP base;
- contenido XMP preservado;
- operación propuesta y campos afectados;
- herramienta/versión que la generó;
- fecha, estado y relación con la versión anterior.

No se confiará únicamente en timestamps para detectar cambios.

## Puntuaciones y selecciones

La puntuación XMP observada y la selección interna son datos distintos:

- `rating XMP`: metadato leído del sidecar y posiblemente sincronizado con Lightroom;
- `selección interna`: decisión registrada en SQLite por este workflow.

El sistema no debe asumir que ambos valores coinciden ni escribir uno sobre el otro sin una acción explícita.

## Ajustes y máscaras ACR

Los ajustes ACR pueden variar según la versión de proceso y las versiones de Lightroom/Camera Raw. Las máscaras pueden incluir estructuras complejas y datos que el sistema no entienda.

La estrategia inicial es de preservación:

- analizar campos necesarios de forma selectiva;
- mantener namespaces, atributos y nodos no reconocidos;
- evitar reserializar todo el documento si eso altera datos no relacionados;
- probar propuestas contra fixtures sintéticos de distintas versiones;
- no prometer equivalencia visual sin abrir el resultado en una versión soportada de Lightroom/ACR.

## Flujo manual con Lightroom

1. Lightroom o el usuario genera/sincroniza sidecars XMP cuando corresponde.
2. El workflow lee una instantánea de esos archivos.
3. El usuario revisa propuestas fuera de la carpeta RAW.
4. Tras una aplicación explícita, el usuario indica a Lightroom que lea los metadatos desde archivo.
5. Si Lightroom produjo cambios nuevos, el workflow debe volver a analizar y crear una versión nueva, no sobrescribir el historial.

La dirección de sincronización debe mostrarse claramente para evitar que “guardar metadatos” y “leer metadatos” se confundan.

## Casos de conflicto

- Lightroom modificó el XMP después del análisis.
- El sidecar fue creado o eliminado fuera de la aplicación.
- El RAW fue movido, renombrado o reemplazado.
- La versión de ACR no reconoce un ajuste o una máscara.
- Varias aplicaciones escriben metadatos con serializaciones distintas.

Ante un conflicto, el comportamiento por defecto será detener la escritura, conservar ambas versiones y solicitar revisión.

## Decisiones pendientes

- Versiones mínimas y máximas de Lightroom Classic/ACR soportadas.
- Campos XMP que el MVP podrá proponer modificar.
- Método de preservación XML y comparación semántica.
- Convención exacta de nombres y manifiestos del archivo de versiones.
- Si la aplicación de sidecars forma parte del MVP o queda como operación manual.
- Matriz de pruebas por formato RAW y versión de proceso.
