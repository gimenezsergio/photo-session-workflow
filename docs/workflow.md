# Flujo de trabajo propuesto

## Flujo activo: Fase 0 de posproducción

### 1. Preparar Lightroom y vincular la sesión

1. El usuario termina su selección y edición parcial en Lightroom Classic.
2. Guarda metadatos con `Ctrl+S` para actualizar los sidecars XMP.
3. Vincula una carpeta de sesión externa con hasta 200 fotografías.
4. La aplicación informa que sólo leerá las fuentes y que no puede comprobar directamente el catálogo.

### 2. Inventariar y relacionar

1. Inventariar NEF, JPG, XMP y archivos ACR auxiliares.
2. Relacionarlos por nombre base sin moverlos ni renombrarlos.
3. Leer EXIF y estrellas desde XMP como representación del último estado guardado desde Lightroom en el sidecar.
4. Mostrar archivos incompletos, duplicados, ambiguos o sin XMP.
5. Advertir que las estrellas pueden diferir del catálogo y que XMP es la única fuente accesible.

### 3. Reducir mediante estrellas y proxies

1. Filtrar por estrellas leídas desde XMP.
2. Elegir como fuente de preview un JPG exportado por Lightroom cuando exista o una aproximación extraída/revelada desde NEF.
3. Identificar la procedencia en cada preview; nunca presentar ambas fuentes como equivalentes.
4. Generar proxies JPG sRGB en el workspace privado, con 2048 px de lado largo por defecto y calidad aproximada de 85.
5. Excluir metadatos sensibles innecesarios.
6. Generar una hoja de contacto para la revisión general.

### 4. Confirmar la selección reducida

1. El usuario revisa proxies y hoja de contacto.
2. La aplicación puede sugerir similares o posibles seleccionadas, sin modificar la selección.
3. El usuario confirma explícitamente aproximadamente 12 a 30 fotografías.
4. Sólo las fotografías confirmadas pasan al análisis visual detallado.

### 5. Analizar y confirmar resultados

1. Analizar exposición, dominantes de color, coherencia de serie y similitud.
2. Presentar posibles seleccionadas, ajustes globales y máscaras recomendadas como sugerencias.
3. Identificar limitaciones derivadas del tipo de preview.
4. Permitir que el usuario confirme, rechace o deje pendiente cada resultado.
5. No escribir sugerencias en Lightroom, XMP ni archivos fotográficos.

## Flujo futuro fuera de la Fase 0

## 1. Preparar una sesión

1. Crear la sesión con título, objetivo, fecha tentativa y estado.
2. Asociar un perfil de modelo mediante alias.
3. Definir estilo, locación, vestuario y referencias.
4. Redactar por separado:
   - una propuesta apta para compartir con la modelo;
   - un plan interno del fotógrafo.
5. Revisar que la propuesta no contenga notas internas ni datos sensibles innecesarios.

## 2. Vincular material fotográfico en fases futuras

1. Elegir una carpeta RAW ya existente.
2. Confirmar que se tratará como fuente de solo lectura.
3. Crear un registro de importación con la ruta, fecha y opciones, sin copiar automáticamente los originales.
4. Inventariar archivos compatibles y detectar sidecars asociados.
5. Registrar huellas para reconocer cambios posteriores.

“Importar” en este sistema significa registrar y analizar referencias; no significa mover archivos ni importarlos al catálogo Lightroom.

## 3. Analizar en fases futuras

1. Extraer una miniatura embebida o generar una previsualización en el workspace.
2. Leer EXIF y normalizar únicamente campos conocidos, preservando el resultado bruto cuando sea útil.
3. Leer XMP disponible y recuperar rating, ajustes y presencia de máscaras.
4. Marcar advertencias por archivos ausentes, sidecars inválidos o metadatos incompatibles.
5. Calcular grupos sugeridos por ráfaga o similitud cuando esa función esté habilitada.

## 4. Revisar y seleccionar en fases futuras

1. Navegar por miniaturas sin abrir o alterar los RAW.
2. Revisar grupos similares y corregir su composición si hace falta.
3. Asignar decisiones propias del workflow, por ejemplo: pendiente, candidata, seleccionada o descartada.
4. Diferenciar esas decisiones de la puntuación XMP observada.
5. Generar hojas de contacto con identificadores que permitan volver al activo fuente.

## 5. Preparar cambios XMP en fases futuras

1. Seleccionar fotos y definir el cambio propuesto.
2. Tomar como base el XMP actual o una plantilla compatible.
3. Guardar un snapshot inmutable del original, o registrar explícitamente que no existía.
4. Generar una nueva versión en `xmp_proposals`, sin escribir junto al RAW.
5. Mostrar un resumen de diferencias y advertencias.

## 6. Aplicar y sincronizar en fases futuras

La aplicación de propuestas requiere una decisión de diseño pendiente. Si se habilita:

1. El usuario confirma de forma explícita los archivos afectados.
2. Se verifica que el RAW y el XMP fuente no cambiaron desde la propuesta.
3. Se archiva nuevamente el sidecar vigente.
4. Se escribe de manera atómica el sidecar, nunca el RAW.
5. El usuario solicita a Lightroom que lea los metadatos desde archivo.
6. Se registra el resultado y la ruta de restauración.

El sistema no automatizará cambios dentro de `.lrcat`.

Nada de este flujo futuro habilita escritura o recuperación XMP en la Fase 0.

## Estados sugeridos para revisar

- Sesión: idea, preproducción, confirmada, realizada, en selección, entregada, archivada.
- Activo: descubierto, analizado, advertencia, no compatible, ausente.
- Selección: sin revisar, candidata, seleccionada, descartada.
- Propuesta XMP: borrador, validada, aplicada, obsoleta, revertida.

Estas taxonomías son propuestas y deben validarse antes de fijar el esquema de datos.
