# Fase 0: posproducción asistida en modo lectura

## Objetivo

Construir una herramienta local para revisar fotografías que ya fueron seleccionadas y editadas parcialmente en Lightroom Classic. La herramienta reducirá una sesión de hasta 200 fotografías mediante estrellas, proxies y una hoja de contacto; el usuario confirmará una selección de aproximadamente 12 a 30 fotografías antes del análisis visual detallado.

Lightroom Classic seguirá siendo el editor principal. La aplicación sólo presentará información y sugerencias; las decisiones creativas y técnicas finales serán siempre del usuario.

## Alcance cerrado

### Entradas

- NEF de Nikon D7000.
- JPG, incluidos los exportados desde Lightroom.
- Sidecars XMP guardados por Lightroom mediante `Ctrl+S`.
- Archivos ACR auxiliares encontrados en la carpeta de sesión.

### Lecturas

- Inventario de archivos.
- Relaciones por nombre base entre NEF, XMP, ACR y JPG.
- EXIF necesario para identificación y análisis.
- Estrellas presentes en XMP, interpretadas como el último estado guardado desde Lightroom en el sidecar.
- Presencia de ajustes y máscaras ACR cuando puedan identificarse sin modificar el documento.

### Derivados privados

- Proxy JPG.
- Espacio de color sRGB.
- Lado largo configurable, 2048 px por defecto.
- Calidad JPEG aproximada de 85.
- Sin GPS, rutas absolutas ni metadatos sensibles innecesarios.
- Almacenamiento exclusivo dentro del workspace privado configurado, fuera de Git y de la sesión fuente.
- Hoja de contacto creada a partir de proxies.

### Fuentes de preview

1. `lightroom_export`: JPG exportado desde Lightroom, usado para representar mejor la edición visible.
2. `nef_approximation`: preview embebido o revelado desde NEF, mostrado como aproximación.

Cada proxy debe conservar su procedencia. La interfaz y los informes no deben presentar las dos fuentes como visualmente equivalentes.

### Resultados permitidos

- Advertencias de inventario, asociación y metadatos.
- Filtro por estrellas.
- Hoja de contacto.
- Selección reducida confirmada por el usuario.
- Sugerencias sobre exposición, dominantes de color, coherencia de la serie, similitud, posibles seleccionadas, ajustes globales y máscaras.
- Confirmación, rechazo o estado pendiente para cada sugerencia.

## Prohibiciones de la Fase 0

- No modificar XMP ni archivos ACR.
- No modificar NEF, JPG, TIFF ni DNG.
- No abrir ni escribir catálogos `.lrcat`.
- No crear, aplicar ni restaurar versiones XMP/ACR.
- No eliminar archivos fuente ni derivados.
- No mover ni renombrar archivos de la sesión.
- No aplicar automáticamente sugerencias.
- No analizar visualmente en detalle fotografías que el usuario no haya confirmado.

## Flujo funcional

1. El usuario guarda metadatos en Lightroom Classic con `Ctrl+S`.
2. Vincula la carpeta externa de una sesión.
3. La aplicación valida que el workspace no esté dentro de la sesión ni del repositorio.
4. Inventaría NEF, XMP, ACR y JPG sin escribir en la carpeta.
5. Relaciona archivos por nombre base y muestra ambigüedades o faltantes.
6. Lee EXIF y estrellas desde XMP como último estado guardado desde Lightroom en el sidecar.
7. Advierte que XMP es la única fuente accesible y puede estar desactualizado respecto del catálogo.
8. El usuario filtra por estrellas.
9. La aplicación elige o permite elegir la fuente de preview y deja registrada su procedencia.
10. Genera proxies y una hoja de contacto en el workspace privado.
11. El usuario confirma una selección reducida de aproximadamente 12 a 30 fotografías.
12. La aplicación analiza visualmente sólo la selección confirmada.
13. Presenta sugerencias con sus limitaciones y nivel de confianza cuando corresponda.
14. El usuario confirma, rechaza o deja pendiente cada resultado.
15. Toda edición posterior se realiza manualmente en Lightroom Classic.

## Tareas pequeñas y criterios de aceptación

### P0-01. Definir el contrato de sesión y rutas

Documentar entradas, workspace y reglas de separación de rutas.

**Criterios de aceptación**

- Existe una raíz de sesión de solo lectura y una raíz de workspace de lectura/escritura.
- La validación rechaza un workspace dentro de la sesión o del repositorio.
- Ninguna ruta real queda codificada ni versionada.

### P0-02. Definir fixtures sintéticos

Preparar casos mínimos que representen NEF D7000, JPG, XMP con y sin estrellas y ACR auxiliar, sin usar fotografías privadas.

**Criterios de aceptación**

- Todos los fixtures son sintéticos o están expresamente habilitados para pruebas.
- Hay casos con archivo faltante, asociación ambigua, XMP inválido y XMP sin rating.
- Ningún fixture contiene GPS, identidad de modelos, credenciales ni rutas personales.

### P0-03. Inventariar archivos

Definir el descubrimiento no destructivo de NEF, JPG, XMP y ACR.

**Criterios de aceptación**

- Un inventario de hasta 200 fotografías termina sin crear, modificar, mover o eliminar archivos fuente.
- Los formatos ajenos se ignoran o informan sin detener el inventario.
- Cada entrada registra tipo, nombre, tamaño y ubicación de forma segura.

### P0-04. Relacionar por nombre base

Construir relaciones entre archivos de una misma fotografía.

**Criterios de aceptación**

- `foto.NEF`, `foto.xmp`, `foto.jpg` y un ACR auxiliar compatible se relacionan con el mismo activo lógico.
- Colisiones por mayúsculas, duplicados o múltiples JPG se muestran como ambigüedades.
- La relación no renombra ni mueve archivos.

### P0-05. Leer EXIF

Definir y extraer el conjunto mínimo de EXIF necesario.

**Criterios de aceptación**

- Se recuperan, cuando existen, fecha/hora, cámara, lente, exposición, ISO y dimensiones.
- La ausencia o corrupción de EXIF produce una advertencia y no altera el archivo.
- GPS no se copia a proxies ni hojas de contacto.

### P0-06. Leer estrellas desde XMP

Interpretar el rating XMP sin consultar `.lrcat`.

**Criterios de aceptación**

- Se distinguen ratings válidos, ausentes e inválidos.
- La interfaz indica que el valor proviene de XMP y recuerda guardar con `Ctrl+S`.
- La interfaz explica que el rating representa el último estado guardado desde Lightroom en el sidecar, no el estado actual comprobado del catálogo.
- Se muestra una advertencia de posible desactualización respecto del catálogo.
- Ningún `.lrcat` se abre durante la operación.

### P0-07. Filtrar por estrellas

Permitir reducir el inventario antes de generar o analizar derivados.

**Criterios de aceptación**

- El usuario puede elegir el umbral o conjunto de estrellas.
- El conteo antes y después del filtro es visible.
- El filtro no modifica XMP ni la selección de Lightroom.

### P0-08. Resolver la fuente de preview

Elegir entre JPG de Lightroom y aproximación desde NEF.

**Criterios de aceptación**

- Cada preview queda marcado como `lightroom_export` o `nef_approximation`.
- Si existen ambas fuentes, la elección es visible y revisable.
- Una aproximación NEF incluye una advertencia de que puede diferir de Lightroom.

### P0-09. Generar proxies

Crear derivados privados para revisión eficiente.

**Criterios de aceptación**

- La salida es JPG sRGB con 2048 px de lado largo por defecto y tamaño configurable.
- La calidad configurada por defecto es aproximadamente 85.
- El proxy no incluye GPS, rutas absolutas ni metadatos sensibles innecesarios.
- El archivo se escribe sólo en el workspace privado.
- Repetir la operación con la misma entrada y configuración no duplica proxies.

### P0-10. Generar la hoja de contacto

Crear una vista general a partir de proxies.

**Criterios de aceptación**

- Cada celda permite identificar el activo lógico, rating XMP y fuente de preview.
- La hoja usa proxies y no vuelve a revelar individualmente todos los NEF.
- La salida queda dentro del workspace y no expone rutas absolutas ni GPS.

### P0-11. Confirmar la selección reducida

Registrar una decisión explícita del usuario antes del análisis detallado.

**Criterios de aceptación**

- El usuario puede añadir y quitar fotografías antes de confirmar.
- La confirmación muestra el conteo y recomienda un rango de 12 a 30 sin imponerlo silenciosamente.
- No se inicia análisis detallado sin confirmación explícita.
- La confirmación no escribe estrellas ni selecciones en Lightroom/XMP.

### P0-12. Analizar la selección confirmada

Evaluar únicamente los proxies confirmados.

**Criterios de aceptación**

- Ninguna fotografía fuera de la selección confirmada recibe análisis detallado.
- Los resultados separan observaciones de exposición, color, coherencia, similitud y selección sugerida.
- Cada resultado identifica la fuente y las limitaciones del preview.
- Un error en una fotografía no invalida el resto del análisis.

### P0-13. Presentar recomendaciones de edición

Describir posibles ajustes globales y máscaras sin generarlos ni aplicarlos.

**Criterios de aceptación**

- Las recomendaciones se muestran como texto o datos internos no ejecutables.
- No se crea ni modifica XMP/ACR.
- No se afirma que una máscara recomendada sea equivalente a una máscara de Lightroom.

### P0-14. Confirmar resultados

Mantener al usuario como responsable de cada decisión final.

**Criterios de aceptación**

- Cada sugerencia puede quedar confirmada, rechazada o pendiente.
- No existe una acción que aplique resultados automáticamente.
- El estado confirmado se almacena sólo en la base local del workflow.

### P0-15. Verificar límites de seguridad

Ejecutar pruebas de no modificación y separación de datos.

**Criterios de aceptación**

- Checksums de todos los archivos fuente son idénticos antes y después del flujo.
- No se abren ni crean archivos `.lrcat`.
- No aparecen RAW, JPG de producción, XMP, ACR, proxies, hojas de contacto ni configuración local en Git.
- No se elimina ningún archivo.
- Todas las escrituras observadas pertenecen al workspace privado autorizado.

### P0-16. Verificar volumen objetivo

Probar el recorrido completo con una sesión representativa de hasta 200 fotografías.

**Criterios de aceptación**

- El inventario, filtrado, generación de proxies y hoja de contacto completan sin procesar visualmente en detalle las 200 fotografías.
- El análisis detallado se limita a la selección confirmada.
- Se registran tiempos y uso de almacenamiento para decidir objetivos de rendimiento posteriores.

## Definición de terminado de la Fase 0

La Fase 0 estará terminada cuando todas las tareas P0-01 a P0-16 cumplan sus criterios, el flujo opere con fixtures y una copia de prueba representativa de Nikon D7000, y se demuestre mediante checksums y auditoría de escrituras que ninguna fuente fue modificada o eliminada.

## Decisiones futuras no bloqueantes

- Herramientas concretas para EXIF, decodificación NEF, gestión de color y generación de proxies.
- Convención exacta para identificar JPG exportados desde Lightroom cuando hay múltiples versiones.
- Semántica de los archivos ACR auxiliares reales encontrados en sesiones.
- Umbrales, métricas y presentación de confianza de cada análisis visual.
- Algoritmo de similitud y agrupación automática avanzada.
- Política manual de retención y limpieza de proxies y hojas de contacto.
- Preproducción, propuesta creativa interna, propuesta para la modelo y planificación.
- Escritura, versionado, aplicación y recuperación XMP/ACR.
- Versiones adicionales de cámaras, formatos RAW y Lightroom/Camera Raw.
- Cifrado o controles adicionales del workspace en equipos compartidos.
