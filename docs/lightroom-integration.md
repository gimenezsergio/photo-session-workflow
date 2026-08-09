# Integración con Lightroom Classic y ACR

## Alcance

El MVP se integrará mediante archivos XMP y convenciones compatibles con Adobe Camera Raw. El catálogo `.lrcat` se considera una fuente fuera de límites: podrá registrarse su ubicación como referencia, pero no se abrirá para escritura ni se modificará directamente.

En la Fase 0, Lightroom Classic es el editor principal y la integración es estrictamente de lectura. La aplicación no abrirá el catálogo `.lrcat`, no modificará XMP/ACR, no aplicará ni restaurará versiones y no escribirá ajustes sugeridos.

## Modelo de interacción

### Lectura

- Detectar el sidecar asociado a cada RAW según su nombre y ubicación.
- Leer XML con namespaces XMP/RDF y campos ACR conocidos.
- Recuperar la puntuación por estrellas cuando esté presente.
- Inventariar ajustes de revelado y presencia de estructuras de máscaras.
- Conservar campos desconocidos sin interpretarlos ni descartarlos.
- Usar las estrellas del XMP como única fuente accesible; representan el último estado que el usuario guardó desde Lightroom en el sidecar mediante `Ctrl+S`.
- Advertir que no puede comprobarse automáticamente una discrepancia con el catálogo porque la Fase 0 no abre `.lrcat`.
- Inventariar archivos ACR auxiliares encontrados y relacionarlos por nombre base, sin asumir todavía su semántica.

### Previews de la Fase 0

- Preferir un JPG exportado desde Lightroom cuando se necesite representar la edición visible.
- Aceptar una previsualización extraída o revelada desde NEF como aproximación.
- Registrar y mostrar la procedencia de cada preview.
- No afirmar equivalencia visual entre ambos tipos.
- Generar el proxy derivado como JPG sRGB, con lado largo configurable —2048 px inicial— y calidad aproximada de 85.

## Capacidades futuras fuera de la Fase 0

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

Estas capacidades no forman parte de la Fase 0 y no deben estar disponibles mediante interfaz, servicio o adaptador activo.

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

### Fase 0

1. El usuario selecciona y edita parcialmente en Lightroom Classic.
2. Guarda metadatos con `Ctrl+S`.
3. El workflow lee XMP, EXIF y archivos relacionados sin escribir.
4. El usuario revisa proxies, confirma una selección reducida y genera un paquete local para revisión asistida.
5. Si lo desea, carga manualmente ese paquete en ChatGPT; la aplicación no controla Lightroom ni ChatGPT.
6. El usuario registra manualmente las recomendaciones y realiza cualquier edición posterior en Lightroom.

### Futuro

1. El usuario revisa propuestas XMP fuera de la carpeta RAW.
2. Tras una aplicación explícita, solicita a Lightroom que lea los metadatos desde archivo.
3. Si Lightroom produjo cambios nuevos, el workflow vuelve a analizar y crea una versión nueva sin sobrescribir el historial.

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
- Semántica y formatos reales de los archivos ACR auxiliares que aparezcan en las sesiones.
- Método para representar recomendaciones de máscaras sin escribirlas.
- Posible importación estructurada futura de recomendaciones producidas fuera de la aplicación.
