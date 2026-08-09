# Flujo de trabajo propuesto

## 1. Preparar una sesión

1. Crear la sesión con título, objetivo, fecha tentativa y estado.
2. Asociar un perfil de modelo mediante alias.
3. Definir estilo, locación, vestuario y referencias.
4. Redactar por separado:
   - una propuesta apta para compartir con la modelo;
   - un plan interno del fotógrafo.
5. Revisar que la propuesta no contenga notas internas ni datos sensibles innecesarios.

## 2. Vincular material fotográfico

1. Elegir una carpeta RAW ya existente.
2. Confirmar que se tratará como fuente de solo lectura.
3. Crear un registro de importación con la ruta, fecha y opciones, sin copiar automáticamente los originales.
4. Inventariar archivos compatibles y detectar sidecars asociados.
5. Registrar huellas para reconocer cambios posteriores.

“Importar” en este sistema significa registrar y analizar referencias; no significa mover archivos ni importarlos al catálogo Lightroom.

## 3. Analizar

1. Extraer una miniatura embebida o generar una previsualización en el workspace.
2. Leer EXIF y normalizar únicamente campos conocidos, preservando el resultado bruto cuando sea útil.
3. Leer XMP disponible y recuperar rating, ajustes y presencia de máscaras.
4. Marcar advertencias por archivos ausentes, sidecars inválidos o metadatos incompatibles.
5. Calcular grupos sugeridos por ráfaga o similitud cuando esa función esté habilitada.

## 4. Revisar y seleccionar

1. Navegar por miniaturas sin abrir o alterar los RAW.
2. Revisar grupos similares y corregir su composición si hace falta.
3. Asignar decisiones propias del workflow, por ejemplo: pendiente, candidata, seleccionada o descartada.
4. Diferenciar esas decisiones de la puntuación XMP observada.
5. Generar hojas de contacto con identificadores que permitan volver al activo fuente.

## 5. Preparar cambios XMP

1. Seleccionar fotos y definir el cambio propuesto.
2. Tomar como base el XMP actual o una plantilla compatible.
3. Guardar un snapshot inmutable del original, o registrar explícitamente que no existía.
4. Generar una nueva versión en `xmp_proposals`, sin escribir junto al RAW.
5. Mostrar un resumen de diferencias y advertencias.

## 6. Aplicar y sincronizar (límite futuro del MVP)

La aplicación de propuestas requiere una decisión de diseño pendiente. Si se habilita:

1. El usuario confirma de forma explícita los archivos afectados.
2. Se verifica que el RAW y el XMP fuente no cambiaron desde la propuesta.
3. Se archiva nuevamente el sidecar vigente.
4. Se escribe de manera atómica el sidecar, nunca el RAW.
5. El usuario solicita a Lightroom que lea los metadatos desde archivo.
6. Se registra el resultado y la ruta de restauración.

El sistema no automatizará cambios dentro de `.lrcat`.

## Estados sugeridos para revisar

- Sesión: idea, preproducción, confirmada, realizada, en selección, entregada, archivada.
- Activo: descubierto, analizado, advertencia, no compatible, ausente.
- Selección: sin revisar, candidata, seleccionada, descartada.
- Propuesta XMP: borrador, validada, aplicada, obsoleta, revertida.

Estas taxonomías son propuestas y deben validarse antes de fijar el esquema de datos.
