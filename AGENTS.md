# AGENTS.md

## Alcance del repositorio

Estas instrucciones aplican a todo el proyecto.

## Estado actual

La implementación está autorizada exclusivamente para P0-01 a P0-11, con recortes explícitos de P0-08 a P0-10 basados en exportaciones Lightroom declaradas:

- contrato de sesión, configuración y fronteras de rutas;
- fixtures sintéticos generados durante las pruebas.
- inventario recursivo y no destructivo de metadatos básicos del filesystem.
- relaciones lógicas deterministas entre entradas admitidas del inventario.
- lectura EXIF filtrada mediante un ejecutable ExifTool local configurado por el usuario.
- lectura acotada de `xmp:Rating`, filtrado puro por estrellas y manifiesto preliminar en memoria con candidato JPG exacto.
- inventario separado de una subcarpeta de exportación declarada, resolución exacta de JPG para activos seleccionados, manifiesto 0.2 y ZIP local sin hoja de contacto.
- proxies privados re-encodificados desde exportaciones Lightroom resueltas y una hoja de contacto construida exclusivamente desde esos proxies.
- borrador y confirmación explícita de una selección reducida en memoria antes de generar cualquier paquete.

Hasta una nueva autorización:

- no generar aproximaciones desde NEF ni ampliar la resolución exacta autorizada;
- no interpretar del XMP nada distinto de `xmp:Rating`, ni interpretar ACR, decodificar NEF o decodificar JPG fuera de las exportaciones Lightroom resueltas para P0-09;
- no inicializar Flask ni SQLite;
- no instalar dependencias sin justificación previa;
- no procesar fotografías reales;
- no abrir, copiar ni modificar catálogos Lightroom.
- no ampliar el paquete, implementar descarga o registrar recomendaciones de P0-12 a P0-14.

## Alcance activo de la Fase 0

- Trabajar con sesiones ya seleccionadas y editadas parcialmente en Lightroom Classic.
- Soportar inicialmente Nikon NEF de una Nikon D7000, JPG, sidecars XMP y archivos ACR auxiliares.
- Leer inventario, relaciones por nombre base, EXIF y estrellas desde XMP después de que el usuario guarde metadatos en Lightroom con `Ctrl+S`; las estrellas representan únicamente el último estado guardado en el sidecar.
- Generar proxies JPG sRGB y hojas de contacto en un workspace privado externo.
- Permitir que el usuario confirme una selección reducida antes de preparar el paquete local para análisis visual asistido.
- Generar el paquete únicamente con la selección confirmada, sin transmitirlo automáticamente.
- Tratar las sugerencias como resultados de una revisión asistida externa iniciada manualmente por el usuario, no como cálculos internos de la aplicación.

Quedan fuera de la Fase 0 la preproducción, las propuestas creativas, las presentaciones para modelos, la agrupación automática avanzada y cualquier escritura o recuperación XMP.

## Reglas permanentes de seguridad de datos

- Tratar NEF, JPG, TIFF, DNG, catálogos `.lrcat`, sidecars XMP y archivos ACR existentes como entradas de solo lectura.
- Nunca modificar, sobrescribir ni eliminar una fotografía original.
- En la Fase 0, nunca abrir ni escribir un catálogo `.lrcat`.
- En la Fase 0, nunca modificar, crear, aplicar ni restaurar XMP/ACR junto a las fuentes.
- Guardar miniaturas, proxies, hojas de contacto e índices de la Fase 0 únicamente en el workspace privado configurado fuera de las fuentes y del repositorio.
- No incluir fotografías reales, catálogos, credenciales, datos personales ni archivos privados de modelos en Git, fixtures o logs.
- Usar datos sintéticos generados en directorios temporales durante las pruebas.

## Límites de arquitectura

- Stack previsto: Python, Flask, SQLite, HTML, CSS y JavaScript vanilla.
- Ejecución local en Windows; no asumir servicios cloud.
- Mantener separadas las capas de dominio, persistencia, análisis de medios, integración XMP y presentación web.
- Las rutas externas deben venir de configuración local ignorada por Git; nunca codificarlas en el código.
- Toda operación futura que escriba archivos debe ser idempotente cuando sea posible, auditable y reversible.
- La capacidad de lectura de la Fase 0 no debe compartir una ruta de código con futuras escrituras sobre fuentes.
- No incorporar en la Fase 0 adaptadores para escribir XMP, acceder a `.lrcat` o controlar Lightroom directamente.
- No incorporar integración con ChatGPT, APIs externas, carga automática ni almacenamiento de credenciales.
- P0-03 sólo puede observar nombres y metadatos del filesystem: no debe abrir el contenido de archivos admitidos, ignorados o prohibidos.
- Los resultados de inventario deben usar rutas relativas y mensajes sanitizados; no deben exponer raíces absolutas.
- P0-04 sólo puede relacionar modelos ya admitidos por P0-03; no debe volver a recorrer el filesystem ni abrir contenidos.
- Las relaciones se limitan al directorio relativo y al nombre sin la última extensión comparado con `casefold()`; no deben inferir sufijos de exportación.
- Toda entrada admitida debe quedar representada exactamente una vez y toda duplicidad o colisión debe permanecer visible.
- P0-05 sólo puede ejecutar ExifTool sobre un único NEF o, en su ausencia, un único JPG/JPEG de un activo no ambiguo.
- Los comandos ExifTool deben construirse internamente mediante una allowlist fija, una lista de argumentos y `shell=False`; nunca deben aceptar flags libres ni argumentos con `=`.
- La salida EXIF debe filtrarse a los campos permitidos y nunca conservar rutas absolutas, GPS, números de serie, propietario, copyright, comentarios, MakerNotes ni stderr crudo.
- ExifTool es una dependencia local externa: no descargar, instalar ni versionar el ejecutable o su carpeta auxiliar.
- La lectura XMP debe limitarse a un sidecar no ambiguo validado por `SessionReader`, con tamaño acotado y rechazo de `DOCTYPE`/`ENTITY`.
- P0-07 sólo filtra modelos en memoria; nunca cambia ratings ni escribe XMP.
- Un JPG relacionado exactamente por P0-04 es sólo `jpg_candidate`; no afirmar que fue exportado por Lightroom.
- El manifiesto preliminar es determinista, permanece en memoria y no contiene imágenes, EXIF completo, contenido XMP, GPS, rutas absolutas ni timestamps de generación.
- La carpeta configurada mediante `lightroom_export_relative_directory` es una subcarpeta relativa, existente y declarada por el usuario; sólo sus JPG/JPEG directos pueden considerarse exportaciones Lightroom, sin verificar su historial real.
- El inventario de exportaciones es separado, no recursivo y no interpreta XMP. Los JPG de cámara del inventario principal nunca sustituyen una exportación declarada dentro del paquete.
- La resolución usa exclusivamente el nombre base exacto comparado con `casefold()`; faltantes, duplicados, entradas inválidas y sufijos no inferidos bloquean un paquete incompleto.
- El ZIP autorizado contiene sólo `manifest.json` 0.2 e imágenes JPG/JPEG resueltas bajo `images/`, se publica exclusivamente en el workspace y nunca se transmite.
- No afirmar que el empaquetado elimina EXIF incrustado: la política de metadatos depende de la configuración de exportación utilizada en Lightroom.
- P0-09 sólo puede decodificar los JPG/JPEG `resolved` dentro de la carpeta Lightroom declarada. Los NEF, JPG de cámara, XMP, ACR y catálogos quedan fuera de esa ruta de lectura.
- Los proxies deben aplicar orientación EXIF, convertir perfiles ICC válidos a sRGB, limitar bytes y píxeles, y re-encodificar sin copiar EXIF, XMP, comentarios ni otros metadatos fuente. Ante ausencia de perfil sólo se admite asumir sRGB para imágenes RGB o escala de grises y debe advertirse.
- Proxies y hojas de contacto usan nombres relativos derivados del contenido, publicación exclusiva y verificación byte por byte antes de reutilizar un resultado existente. No sobrescribir ni eliminar derivados automáticamente.
- P0-10 debe leer exclusivamente proxies privados verificados por hash. Una tanda incompleta o alterada bloquea la hoja de contacto.
- P0-11 debe derivar candidatos únicamente de una tanda completa de proxies, permitir altas y bajas puras por `asset_id` y exigir `explicit_confirmation=True`. El rango 12–30 es una recomendación visible, nunca un bloqueo; una sesión de cinco o siete imágenes puede confirmarse.
- La confirmación debe sellar identificador, rating, procedencia, rutas relativas y hashes de fuente/proxy. El paquete existente debe rechazar confirmaciones ausentes, inconsistentes o correspondientes a una exportación que cambió después de generar el proxy.
- Pillow es la única dependencia de ejecución incorporada para este recorte; no utilizar ejecutables de imagen, red ni servicios externos.
- No generar aproximaciones NEF, ampliar P0-12, iniciar Flask/SQLite ni agregar persistencia hasta nueva autorización.

## Criterios para cambios futuros

- Actualizar la documentación cuando cambie una decisión de diseño.
- Añadir pruebas con fixtures mínimos y sintéticos antes de procesar sesiones reales.
- Verificar en copias de prueba cualquier comportamiento dependiente de Lightroom Classic o Adobe Camera Raw.
- Evitar ampliar el MVP sin registrar la decisión y su impacto en privacidad y recuperación.
- No implementar funciones fuera de `docs/phase-0-postproduction.md` mientras la Fase 0 sea el alcance activo.
