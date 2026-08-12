# Fase 0: posproducción asistida en modo lectura

## Objetivo

Construir una herramienta local para revisar fotografías que ya fueron seleccionadas y editadas parcialmente en Lightroom Classic. La herramienta reducirá una sesión de hasta 200 fotografías mediante estrellas, proxies y una hoja de contacto; el usuario confirmará una selección de aproximadamente 12 a 30 fotografías y la aplicación preparará únicamente esa selección para análisis visual asistido.

Lightroom Classic seguirá siendo el editor principal. La aplicación preparará un paquete local que el usuario podrá cargar manualmente en ChatGPT para una revisión conversacional externa. La aplicación no controlará ChatGPT, no usará su API, no almacenará credenciales y no transmitirá archivos automáticamente. Las decisiones creativas y técnicas finales serán siempre del usuario.

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
- Paquete de revisión local con hoja de contacto, proxies seleccionados y manifiesto JSON minimizado.
- Descarga manual del paquete iniciada por el usuario.
- Registro manual de recomendaciones obtenidas durante una revisión asistida externa.
- Confirmación, rechazo o estado pendiente para cada recomendación registrada.

### Contenido del paquete de revisión

- Hoja de contacto.
- Proxies correspondientes únicamente a la selección confirmada.
- Manifiesto JSON sin rutas absolutas, GPS ni datos personales.
- Procedencia de cada preview.
- Rating leído desde XMP.
- Datos técnicos mínimos necesarios para el análisis.
- Identificador o nombre de archivo que permita volver al activo en Lightroom.

El paquete se genera y conserva localmente. El usuario decide si lo descarga y carga manualmente en ChatGPT. La aplicación no conoce ni registra si esa carga externa ocurrió.

## Prohibiciones de la Fase 0

- No modificar XMP ni archivos ACR.
- No modificar NEF, JPG, TIFF ni DNG.
- No abrir ni escribir catálogos `.lrcat`.
- No crear, aplicar ni restaurar versiones XMP/ACR.
- No eliminar archivos fuente ni derivados.
- No mover ni renombrar archivos de la sesión.
- No aplicar automáticamente sugerencias.
- No transmitir automáticamente fotografías, proxies, XMP ni metadatos a servicios externos.
- No controlar ChatGPT, utilizar su API ni almacenar credenciales.
- No incluir en el paquete fotografías que el usuario no haya confirmado.
- No calcular internamente sugerencias visuales en la Fase 0.

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
12. La aplicación genera localmente un paquete de revisión limitado a la selección confirmada.
13. El usuario revisa y descarga manualmente el paquete si decide compartirlo.
14. El usuario realiza, de manera independiente, una revisión conversacional externa en ChatGPT.
15. El usuario registra manualmente las recomendaciones y las marca como confirmadas, rechazadas o pendientes.
16. Toda edición posterior se realiza manualmente en Lightroom Classic.

## Tareas pequeñas y criterios de aceptación

### P0-01. Definir el contrato de sesión y rutas

Documentar entradas, workspace y reglas de separación de rutas.

**Criterios de aceptación**

- Existe una raíz de sesión de solo lectura y una raíz de workspace de lectura/escritura.
- La validación rechaza un workspace dentro de la sesión o del repositorio.
- Ninguna ruta real queda codificada ni versionada.

**Implementación inicial**

- `config.local.json`, ignorado por Git, define sesión, workspace y repositorio mediante rutas absolutas.
- Las raíces deben existir y ser disjuntas; se rechazan igualdad, anidamiento en ambas direcciones y enlaces o reparse points detectables.
- `SessionReader` sólo expone lectura de archivos existentes; `WorkspaceWriter` es una capacidad separada que sólo escribe dentro del workspace.
- Esta separación reduce el riesgo de que una operación futura de lectura reutilice accidentalmente una interfaz de escritura sobre la sesión.
- `WorkspaceWriter` valida contenido, padre y destino final antes de escribir. Rechaza destinos existentes que sean enlaces, reparse points, junctions o tipos distintos de archivo regular.
- Con `overwrite=True`, exige un archivo regular existente, escribe y sincroniza un temporal en el mismo directorio, lo cierra, revalida las fronteras y publica mediante `os.replace`. El archivo anterior se conserva si falla la escritura previa al reemplazo.
- Con `overwrite=False`, usa creación exclusiva (`xb`) y nunca reemplaza una entrada existente. Ante una excepción controlada intenta eliminar el archivo incompleto, pero la publicación no es atómica: una caída abrupta del proceso o del sistema podría dejar un archivo parcial visible.
- Las revalidaciones reducen errores accidentales y condiciones TOCTOU internas, pero no constituyen un sandbox contra otro proceso local hostil que cambie directorios o entradas simultáneamente.

### P0-02. Definir fixtures sintéticos

Preparar casos mínimos que representen NEF D7000, JPG, XMP con y sin estrellas y ACR auxiliar, sin usar fotografías privadas.

**Criterios de aceptación**

- Todos los fixtures son sintéticos o están expresamente habilitados para pruebas.
- Hay casos con archivo faltante, asociación ambigua, XMP inválido y XMP sin rating.
- Ningún fixture contiene GPS, identidad de modelos, credenciales ni rutas personales.

**Implementación inicial**

- Los fixtures se generan exclusivamente dentro de `TemporaryDirectory` durante las pruebas y desaparecen al finalizar.
- Cubren NEF D7000 simulado, JPG simulado, XMP con/sin rating, rating inválido, XML inválido, ACR auxiliar, faltantes, ambigüedad y diferencias de mayúsculas/minúsculas.
- Los archivos con extensión `.NEF` y `.jpg` contienen marcadores textuales explícitos y no son decodificables. Estas pruebas no validan lectura RAW, render de Nikon D7000 ni decodificación JPEG.
- La suite se ejecuta con `python -m unittest discover -s tests -v` sin dependencias externas.

### P0-03. Inventariar archivos

Definir el descubrimiento no destructivo de NEF, JPG, XMP y ACR.

**Criterios de aceptación**

- Un inventario de hasta 200 fotografías termina sin crear, modificar, mover o eliminar archivos fuente.
- Los formatos ajenos se ignoran o informan sin detener el inventario.
- Cada entrada registra tipo, nombre, tamaño y ubicación de forma segura.

**Implementación inicial**

- `SessionReader.inventory()` delega en una capa de inventario de sólo lectura y no expone la raíz absoluta ni una capacidad de escritura.
- Reconoce `.nef`, `.jpg`, `.jpeg`, `.xmp` y `.acr` sin distinguir mayúsculas; conserva la extensión original y registra su forma normalizada.
- Cada entrada admitida contiene únicamente ruta relativa POSIX, nombre, extensiones, categoría, tamaño, modificación UTC en ISO 8601 con nanosegundos, estado y advertencias.
- Los modelos de entrada, aviso y resultado son inmutables. Los conteos de fotografías, sidecars y auxiliares se mantienen separados.
- El recorrido puede ser recursivo o no recursivo, no abre contenidos, no calcula hashes y no escribe en la sesión ni en el workspace.
- El orden estable usa la ruta relativa completa comparada primero mediante `casefold()` y después por su representación original.
- Los errores de enumeración o metadata se convierten en avisos sanitizados por elemento para continuar cuando sea posible, sin incluir rutas absolutas ni el texto potencialmente sensible de la excepción.
- Symlinks, junctions y reparse points detectables se rechazan y nunca se recorren. La protección cubre errores de la aplicación y rutas accidentales, no cambios hostiles simultáneos del filesystem.
- `.lrcat`, `.lrcat-data` y `.lrdata` se rechazan por nombre antes de consultar sus metadatos y nunca se abren ni recorren.
- Superar el objetivo configurable de 200 fotografías genera la advertencia `photo_volume_exceeds_target` y conserva el inventario completo; no se aplica un límite silencioso.
- P0-03 no relaciona nombres base, no interpreta XMP/XML, no extrae EXIF y no decodifica NEF/JPG.

### P0-04. Relacionar por nombre base

Construir relaciones entre archivos de una misma fotografía.

**Criterios de aceptación**

- `foto.NEF`, `foto.xmp`, `foto.jpg` y un ACR auxiliar compatible se relacionan con el mismo activo lógico.
- Colisiones por mayúsculas, duplicados o múltiples JPG se muestran como ambigüedades.
- La relación no renombra ni mueve archivos.

**Implementación inicial**

- `relate_inventory()` opera exclusivamente sobre `InventoryResult.entries`; los elementos ignorados y rechazados por P0-03 no participan.
- La clave lógica combina el directorio relativo exacto y el nombre sin su última extensión comparado mediante `casefold()`. El mismo nombre base en directorios diferentes produce activos distintos.
- Los componentes preservan como procedencia la entrada inmutable completa del inventario, incluida ruta relativa, nombre, capitalización y extensión originales.
- Los roles son `raw` para NEF, `image` para JPG/JPEG, `sidecar` para XMP y `auxiliary` para ACR.
- Un activo sin ambigüedades que contiene al menos un NEF o JPG/JPEG es `complete`. La falta de XMP, RAW o imagen complementaria queda como advertencia y no descarta el activo.
- Un grupo que contiene sólo XMP o ACR es `incomplete` y conserva todos sus componentes.
- Un activo es `ambiguous` si tiene más de un candidato para cualquier rol o si sus nombres base colisionan únicamente por capitalización. Ningún candidato se elige silenciosamente.
- El identificador usa sólo el directorio relativo y el nombre base normalizado, codificados como texto estable; no depende de timestamps, rutas absolutas ni hashes de contenido y es apto como clave textual futura en SQLite.
- Los activos se ordenan por directorio relativo normalizado y nombre base normalizado; los componentes se ordenan por rol y ruta relativa. La misma entrada produce siempre el mismo resultado.
- El resultado informa conteos por estado y verifica que cada entrada admitida esté representada exactamente una vez.
- Sufijos como `-Edit` o `_v2` no se interpretan: esos JPG forman activos separados. El reconocimiento futuro de variantes exportadas queda fuera de P0-04.
- La relación no recorre el filesystem, no abre NEF/JPG/XMP/ACR, no interpreta metadatos, no calcula hashes y no escribe en sesión ni workspace.

### P0-05. Leer EXIF

Definir y extraer el conjunto mínimo de EXIF necesario.

**Criterios de aceptación**

- Se recuperan, cuando existen, fecha/hora, cámara, lente, exposición, ISO y dimensiones.
- La ausencia o corrupción de EXIF produce una advertencia y no altera el archivo.
- GPS no se copia a proxies ni hojas de contacto.

**Implementación inicial**

- ExifTool es un ejecutable externo configurado localmente; la aplicación no lo descarga, instala ni versiona y no incorpora bibliotecas Python de EXIF.
- La selección de fuente es pura: usa un único NEF; si no existe, usa un único JPG/JPEG. Los activos `ambiguous` y los que sólo contienen XMP/ACR se omiten sin ejecutar ExifTool.
- `SessionReader` valida nuevamente la ruta relativa elegida y sólo entrega la ruta absoluta a la instancia interna confiable de `ExifToolAdapter`. La raíz de sesión no se vuelve pública.
- La colaboración protege contra errores de la aplicación y rutas accidentales; no convierte Python o ExifTool en un sandbox frente a código local hostil o cambios simultáneos del filesystem.
- El comando usa una lista de argumentos, `shell=False`, timeout, JSON, valores numéricos y una allowlist fija de tags. No admite argumentos libres, asignaciones con `=` ni opciones de escritura.
- stdout y stderr se drenan concurrentemente a buffers acotados. El contenido que excede el límite configurable se descarta y produce un error sanitizado; stderr nunca se incorpora al resultado público.
- Sólo se normalizan fecha de captura, fabricante, modelo, lente, exposición, apertura, ISO, distancia focal, ancho, alto y orientación. Todos son opcionales.
- Los fallbacks explícitos son `DateTimeOriginal` → `CreateDate`, `LensModel` → `LensID` → `Lens`, `ImageWidth` → `ExifImageWidth` y `ImageHeight` → `ExifImageHeight`.
- `SourceFile`, GPS, ubicación, propietario, copyright, comentarios, números de serie, rostros, MakerNotes y cualquier clave desconocida se descartan aunque ExifTool los devuelva.
- Los estados públicos son `complete`, `partial`, `unavailable`, `error`, `skipped_ambiguous` y `skipped_no_photographic_file`; los errores usan códigos fijos sin rutas ni texto crudo de excepciones.
- La ruta de `exiftool.exe` debe ser absoluta, regular, externa a sesión, workspace y repositorio, y no atravesar symlinks, junctions o reparse points detectables. Los resultados de versión sólo exponen disponibilidad, versión y estado.
- Las pruebas normales usan un runner falso y archivos marcadores temporales. La integración con ExifTool real se limita a `-ver`, queda separada y omitida salvo activación explícita; no utiliza fotografías.
- P0-05 no interpreta XMP/ACR, no genera proxies y no implementa P0-06.

### P0-06. Leer estrellas desde XMP

Interpretar el rating XMP sin consultar `.lrcat`.

**Criterios de aceptación**

- Se distinguen ratings válidos, ausentes e inválidos.
- La interfaz indica que el valor proviene de XMP y recuerda guardar con `Ctrl+S`.
- La interfaz explica que el rating representa el último estado guardado desde Lightroom en el sidecar, no el estado actual comprobado del catálogo.
- Se muestra una advertencia de posible desactualización respecto del catálogo.
- Ningún `.lrcat` se abre durante la operación.

**Implementación inicial**

- `XmpRatingReader` usa únicamente `xml.etree.ElementTree` y lee exclusivamente `{http://ns.adobe.com/xap/1.0/}Rating` como atributo de `rdf:Description` o como elemento.
- `SessionReader` valida el sidecar relativo no ambiguo, lo abre en modo binario de sólo lectura y permite leer como máximo `xmp.max_bytes` más un byte de control.
- Se rechazan antes del parseo los documentos que superan el límite o contienen `DOCTYPE`/`ENTITY`, incluidos marcadores detectables en UTF-16/UTF-32. ElementTree no recibe resolutores externos.
- Los valores `1..5` son `rated`, `0` es `unrated`, `-1` es `rejected`, la ausencia es `missing` y los valores no permitidos o contradictorios son `invalid`.
- Múltiples valores iguales se aceptan con `duplicate_rating_values`; valores diferentes producen `rating_values_conflict` y no se elige ninguno.
- Activos ambiguos y sidecars múltiples se omiten mediante `skipped_ambiguous_asset` o `skipped_ambiguous_sidecar`. Un activo sin componentes NEF/JPG produce `skipped_no_photographic_file` y su XMP no se abre. XML malformado, prohibido, grande o inaccesible produce `error` con un código sanitizado.
- El resultado sólo conserva identificador, rating normalizado, estado, ruta XMP relativa segura, advertencias y código de error. No conserva XML, rutas absolutas ni texto crudo de excepciones.
- `xmp_last_saved_state_only` recuerda que el rating representa el último estado guardado desde Lightroom mediante `Ctrl+S`, no una comprobación del catálogo.
- No se interpretan ajustes, máscaras, ACR ni otros campos XMP y no se consulta `.lrcat`.

### P0-07. Filtrar por estrellas

Permitir reducir el inventario antes de generar o analizar derivados.

**Criterios de aceptación**

- El usuario puede elegir el umbral o conjunto de estrellas.
- El conteo antes y después del filtro es visible.
- El filtro no modifica XMP ni la selección de Lightroom.

**Implementación inicial**

- `RatingFilter` inmutable admite un mínimo de `1..5` o, de forma mutuamente excluyente, un conjunto exacto no vacío de ratings `1..5`.
- `filter_assets_by_rating()` es pura y mantiene el orden de P0-04. Selecciona sólo resultados `rated` que cumplen el filtro, pertenecen a un activo conocido no ambiguo y conservan al menos un componente NEF/JPG.
- `unrated`, `rejected`, `missing`, `invalid`, `error` y estados omitidos se excluyen por defecto con un motivo explícito; un rating bajo o fuera del conjunto también conserva su motivo.
- El resultado informa total evaluado, seleccionados y excluidos sin cambiar archivos ni valores de rating.
- Un error de lectura se registra por activo y no impide procesar los demás.

### P0-08. Resolver la fuente de preview

Elegir entre JPG de Lightroom y aproximación desde NEF.

**Criterios de aceptación**

- Cada preview queda marcado como `lightroom_export` o `nef_approximation`.
- Si existen ambas fuentes, la elección es visible y revisable.
- Una aproximación NEF incluye una advertencia de que puede diferir de Lightroom.

**Recorte implementado en este bloque**

- Para cada activo seleccionado sólo se observa el único JPG/JPEG ya relacionado exactamente por P0-04 y se registra como `jpg_candidate`.
- `jpg_candidate_unverified` aclara que la coincidencia de nombre no demuestra que el archivo haya sido exportado por Lightroom. La confirmación de procedencia queda futura.
- Si no existe JPG se registra `jpg_candidate_missing`; si hubiera múltiples candidatos no se elige ninguno y se registra `jpg_candidate_ambiguous`.
- Sufijos como `-Edit` o `_v2` no se infieren ni se relacionan. No se decodifica NEF/JPG ni se genera preview o proxy.

**Manifiesto preliminar en memoria**

- El flujo implementado es `InventoryResult → RelationResult → ratings XMP → filtro → candidato JPG → manifiesto preliminar`.
- El manifiesto inmutable incluye versión de esquema, filtro, conteos y, por seleccionado, identificador, rating, nombre, ruta XMP relativa, candidato JPG relativo y advertencias.
- La serialización JSON usa claves ordenadas, separadores estables y no incorpora timestamps. No contiene rutas absolutas, GPS, EXIF completo, contenido XMP, NEF ni imágenes codificadas.
- En el recorte preliminar original el manifiesto no se guarda, copia, empaqueta ni transmite. Flask, SQLite, proxies y hojas de contacto permanecen fuera del alcance implementado.

**Recorte implementado para exportaciones Lightroom declaradas**

- `lightroom_export_relative_directory` declara una subcarpeta relativa existente dentro de la sesión. Esa declaración permite tratar sus JPG/JPEG directos como `lightroom_export`, pero no verifica su historial real en Lightroom.
- La ruta no puede ser vacía, absoluta, `.` ni contener `..`, y se rechazan symlinks, junctions o reparse points detectables. El directorio y cada JPG se revalidan antes de leer.
- El inventario principal permanece no recursivo y separado del inventario de exportaciones. Este último observa únicamente JPG/JPEG directos, no recorre otras subcarpetas y no interpreta XMP.
- Cada activo ya seleccionado se resuelve por nombre base exacto mediante `casefold()`. Los estados son `resolved`, `missing`, `ambiguous` e `invalid`; no se infieren sufijos como `-Edit` o `_v2`.
- Los JPG de cámara continúan siendo candidatos no verificados del inventario principal y nunca se usan como sustituto dentro de este paquete.
- El manifiesto 0.2 registra `lightroom_export`, ruta relativa y advertencias de procedencia declarada y política de metadatos. No contiene rutas absolutas, XML, GPS, EXIF completo ni binarios.

### P0-09. Generar proxies

Crear derivados privados para revisión eficiente.

**Criterios de aceptación**

- La salida es JPG sRGB con 2048 px de lado largo por defecto y tamaño configurable.
- La calidad configurada por defecto es aproximadamente 85.
- El proxy no incluye GPS, rutas absolutas ni metadatos sensibles innecesarios.
- El archivo se escribe sólo en el workspace privado.
- Repetir la operación con la misma entrada y configuración no duplica proxies.

**Recorte implementado desde exportaciones Lightroom declaradas**

- La fuente se limita al único JPG/JPEG `resolved` para cada activo seleccionado dentro de `lightroom_export_relative_directory`; no se abren NEF, JPG de cámara, XMP, ACR ni catálogos.
- Pillow aplica la orientación EXIF antes de retirar metadatos, convierte un perfil ICC válido a sRGB y re-encodifica JPEG con lado largo 2048 y calidad 85 por defecto.
- Cuando falta ICC, sólo RGB y escala de grises pueden asumirse sRGB y el resultado conserva `source_profile_missing_assumed_srgb`. Un perfil inválido o un origen no RGB sin perfil se rechaza.
- La salida incorpora únicamente un perfil ICC sRGB estándar; no copia EXIF, GPS, XMP, comentarios ni otros metadatos fuente.
- Bytes y píxeles de entrada tienen límites configurables antes de completar la decodificación. Los errores se informan por activo con códigos sanitizados y no detienen el registro de los demás resultados.
- Cada proxy tiene un nombre relativo seguro derivado del identificador lógico y de sus bytes renderizados. Se publica exclusivamente en el workspace mediante la capacidad protegida de escritura.
- Cada resultado conserva SHA-256 tanto de la exportación fuente como del proxy renderizado para detectar cambios entre revisión y empaquetado.
- Una repetición reutiliza el proxy sólo si sus bytes coinciden exactamente. Nunca sobrescribe ni elimina derivados; si la entrada o configuración cambia, puede conservarse una versión adicional para limpieza manual futura.
- Este recorte no genera `nef_approximation` y todavía no integra los proxies en el ZIP 0.2 existente.

### P0-10. Generar la hoja de contacto

Crear una vista general a partir de proxies.

**Criterios de aceptación**

- Cada celda permite identificar el activo lógico, rating XMP y fuente de preview.
- La hoja usa proxies y no vuelve a revelar individualmente todos los NEF.
- La salida queda dentro del workspace y no expone rutas absolutas ni GPS.

**Implementación inicial**

- La hoja se construye exclusivamente desde una tanda completa de proxies privados `generated` o `reused`; no vuelve a leer la sesión ni las exportaciones Lightroom.
- Antes de decodificar cada proxy, comprueba su ruta relativa, límite de bytes y SHA-256 contra el resultado inmutable de P0-09. Una tanda incompleta, alterada o ilegible bloquea la hoja.
- Cada celda presenta el nombre identificador, rating XMP y procedencia `lightroom_export`; el orden conserva el orden determinista de la selección.
- Columnas, geometría, calidad y límites de bytes/píxeles son configurables. La salida es JPEG sRGB re-encodificada sin copiar metadatos de los proxies.
- El nombre de salida deriva del SHA-256 del JPEG completo. Repetir la misma operación reutiliza bytes idénticos y no duplica, sobrescribe ni elimina hojas.
- Este recorte no confirma todavía la selección P0-11 ni modifica el paquete de revisión P0-12.

### P0-11. Confirmar la selección reducida

Registrar una decisión explícita del usuario antes de preparar el paquete de revisión.

**Criterios de aceptación**

- El usuario puede añadir y quitar fotografías antes de confirmar.
- La confirmación muestra el conteo y recomienda un rango de 12 a 30 sin imponerlo silenciosamente.
- No se genera el paquete de revisión sin confirmación explícita.
- La confirmación no escribe estrellas ni selecciones en Lightroom/XMP.

**Implementación inicial en memoria**

- `create_selection_draft()` acepta exclusivamente una tanda completa y no vacía de proxies `generated` o `reused`; valida unicidad, rutas relativas, ratings, procedencia y SHA-256 de fuente/proxy.
- El borrador comienza con todos los candidatos o con un subconjunto explícito. `update_selection()` devuelve un modelo nuevo para añadir o quitar `asset_id`, conserva el orden original y rechaza desconocidos, duplicados o instrucciones contradictorias.
- El resumen informa candidatos, seleccionados y `below_recommended`, `within_recommended` o `above_recommended`. El rango 12–30 nunca impide confirmar: sesiones finales de cinco o siete imágenes son válidas.
- `confirm_selection()` exige exactamente `explicit_confirmation=True`, rechaza una selección vacía y produce un modelo inmutable con digest determinista. No usa timestamps, rutas absolutas ni persistencia.
- El generador del ZIP 0.2 existente ahora exige una confirmación válida, limita el manifiesto y las imágenes exactamente a sus activos y bloquea antes de publicar si falta un activo, cambia su resolución o difiere el SHA-256 de la exportación que originó el proxy.
- P0-11 no escribe ratings, XMP, ACR ni selecciones de Lightroom; tampoco inicia Flask o SQLite.

### P0-12. Generar el paquete de revisión

Preparar localmente el material mínimo necesario para revisión asistida.

**Criterios de aceptación**

- El paquete contiene hoja de contacto y proxies únicamente de la selección confirmada.
- Incluye un manifiesto JSON válido sin rutas absolutas, GPS ni datos personales.
- Cada entrada registra procedencia del preview, rating XMP, datos técnicos mínimos e identificador para volver a Lightroom.
- La generación no transmite archivos ni requiere credenciales externas.
- Un error en una fotografía se informa sin incorporar silenciosamente un paquete incompleto.

**Implementación inicial**

- El paquete canónico usa el esquema de manifiesto 0.3 y contiene exactamente `manifest.json`, `contact-sheet.jpg` e `images/<proxy-contenido>.jpg`, con un proxy por activo de la selección confirmada.
- La generación exige una confirmación P0-11 válida, no vacía y consistente con una tanda completa de proxies. Los activos no confirmados nunca se incorporan.
- La hoja de contacto se regenera específicamente para el subconjunto confirmado. Tanto la hoja como cada proxy se leen exclusivamente desde el workspace privado y se verifican por ruta relativa, tamaño y SHA-256 antes de empaquetarse.
- Durante P0-12 no se vuelve a abrir la sesión ni la carpeta de exportaciones: NEF, JPG de cámara, JPG exportados, XMP, ACR y catálogos quedan fuera de la capacidad entregada al generador.
- El manifiesto minimizado conserva identificador para Lightroom, rating XMP, procedencia `lightroom_export`, dimensiones del proxy y advertencias. No contiene rutas o hashes fuente, rutas absolutas, GPS, XML, EXIF completo, datos personales, credenciales ni timestamps.
- Los límites configurables se aplican por proxy, a la hoja de contacto y al contenido/ZIP total antes de publicar. Un elemento ausente, alterado, ilegible o excedido bloquea el paquete completo.
- El manifiesto y el orden ZIP son deterministas, con timestamps internos fijos. Los nombres internos se validan contra rutas absolutas, componentes padre, separadores y colisiones.
- La publicación usa la escritura exclusiva del workspace y nunca reemplaza un paquete existente. Ante error no se publica un ZIP parcial; los proxies y hojas derivados no se eliminan automáticamente.
- El resultado local registra tamaño y SHA-256 del ZIP. El paquete contiene imágenes identificables, permanece local y sólo puede compartirse mediante una acción manual y explícita del usuario; no se transmite ni sube automáticamente.
- El ZIP 0.2 que incorporaba directamente exportaciones Lightroom queda temporalmente como compatibilidad interna del recorte anterior, pero no es el paquete canónico de P0-12.
- Proxies desde NEF, interfaz Flask, descarga P0-13 y persistencia SQLite siguen fuera de este recorte.

### P0-13. Permitir revisar y descargar el paquete

Ofrecer al usuario control explícito sobre el handoff manual.

**Criterios de aceptación**

- Antes de descargar, el usuario puede revisar conteo, archivos incluidos, procedencia y metadatos del manifiesto.
- La interfaz advierte que los proxies contienen imágenes identificables y que compartirlos es decisión del usuario.
- La descarga requiere una acción explícita y no inicia una carga externa.
- La aplicación no controla ChatGPT, no usa su API y no almacena credenciales.

### P0-14. Registrar manualmente recomendaciones y estado

Permitir registrar resultados obtenidos durante la revisión asistida sin importación automática ni aplicación.

**Criterios de aceptación**

- El usuario puede registrar manualmente recomendaciones de exposición, color, coherencia, similitud, selección, ajustes globales y máscaras.
- Cada recomendación puede quedar confirmada, rechazada o pendiente.
- No existe una acción que aplique resultados automáticamente ni que modifique XMP/ACR.
- El estado se almacena sólo en la base local del workflow y conserva referencia al activo correspondiente.

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

- El inventario, filtrado, generación de proxies y hoja de contacto completan sin preparar individualmente las 200 fotografías para revisión asistida.
- El paquete de revisión se limita a la selección confirmada.
- Se registran tiempos y uso de almacenamiento para decidir objetivos de rendimiento posteriores.

## Definición de terminado de la Fase 0

La Fase 0 estará terminada cuando todas las tareas P0-01 a P0-16 cumplan sus criterios, el flujo opere con fixtures y una copia de prueba representativa de Nikon D7000, y se demuestre mediante checksums y auditoría de escrituras que ninguna fuente fue modificada o eliminada.

## Decisiones futuras no bloqueantes

- Herramientas concretas para EXIF, decodificación NEF, gestión de color y generación de proxies.
- Convención exacta para identificar JPG exportados desde Lightroom cuando hay múltiples versiones.
- Semántica de los archivos ACR auxiliares reales encontrados en sesiones.
- Posible análisis visual local y sus métricas de calidad.
- Posible integración mediante API con consentimiento y credenciales separados.
- Posible importación estructurada de resultados de una revisión externa.
- Algoritmo de similitud y agrupación automática avanzada.
- Política manual de retención y limpieza de proxies y hojas de contacto.
- Preproducción, propuesta creativa interna, propuesta para la modelo y planificación.
- Escritura, versionado, aplicación y recuperación XMP/ACR.
- Versiones adicionales de cámaras, formatos RAW y Lightroom/Camera Raw.
- Cifrado o controles adicionales del workspace en equipos compartidos.
