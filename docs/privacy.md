# Privacidad y separación de datos

## Objetivo

Reducir la exposición de fotografías y datos personales mediante almacenamiento local, minimización de datos y separación física entre el repositorio, las fuentes y el área privada.

## Clasificación de información

### Pública o compartible

- propuesta revisada para la modelo;
- referencias cuyo uso compartido esté permitido;
- detalles logísticos estrictamente necesarios.

### Interna del fotógrafo

- plan de tomas;
- criterios de selección;
- notas creativas y técnicas;
- historial de análisis y versiones XMP.

### Privada o sensible

- nombres legales, contacto, documentos y contratos;
- direcciones privadas o datos de acceso a locaciones;
- fotografías no publicadas;
- material íntimo o sujeto a restricciones;
- autorizaciones de imagen y cualquier dato de salud o identificación.

## Reglas del MVP

- Usar alias o identificadores internos para modelos siempre que sea posible.
- No exigir nombre legal, documento, teléfono, correo ni redes sociales.
- Mantener archivos privados en una raíz externa dedicada y no en el repositorio.
- No copiar automáticamente archivos privados al workspace.
- No incluir datos sensibles en nombres de archivo, URLs locales, logs o hojas de contacto.
- Usar fixtures sintéticos en documentación y pruebas.
- No transmitir automáticamente fotografías, proxies, EXIF, XMP ni datos personales a ChatGPT o cualquier servicio externo.
- No usar la API de ChatGPT, controlar su interfaz ni almacenar credenciales en la Fase 0.
- Exigir una decisión y acción explícitas del usuario antes de compartir manualmente un paquete de revisión.
- Escuchar únicamente en `127.0.0.1` por defecto.
- Guardar proxies y hojas de contacto sólo en el workspace privado, nunca en GitHub ni dentro de la sesión fuente.
- Generar proxies sin GPS, rutas absolutas, datos de contacto u otros metadatos sensibles innecesarios.
- Mantener NEF, JPG, TIFF, DNG, XMP y ACR como fuentes de solo lectura en la Fase 0.
- No eliminar archivos durante la Fase 0, incluidos los derivados; cualquier política futura de limpieza será manual y explícita.

## Riesgos relevantes

- El EXIF puede revelar fecha, cámara y ubicación GPS.
- Los paths pueden contener nombres de personas o proyectos privados.
- Las miniaturas y hojas de contacto siguen siendo datos fotográficos sensibles.
- Los proxies de 2048 px pueden ser suficientemente detallados para identificar personas o revelar material no publicado.
- El paquete de revisión sigue conteniendo imágenes identificables aunque sus metadatos hayan sido minimizados.
- Las copias de seguridad y sincronización automática del sistema operativo pueden replicar el workspace.
- Una propuesta compartible puede filtrar notas internas si ambas vistas reutilizan el mismo campo.

## Controles previstos

- Separar campos y plantillas de contenido compartible e interno.
- Omitir GPS y rutas absolutas de exportaciones por defecto.
- En una fase futura, permitir una limpieza manual y explícita de derivados regenerables sin tocar fuentes.
- Registrar acceso y generación de exportaciones de manera local y sin contenido sensible.
- Documentar ubicación, retención y respaldo del workspace.
- Incorporar una revisión previa a toda exportación compartible.
- Registrar la procedencia del preview sin exponer la ruta absoluta de la fuente en la interfaz o exportaciones.
- Minimizar el manifiesto y los proxies antes de generar el paquete: excluir rutas absolutas, GPS, datos personales y metadatos no necesarios.
- Mostrar una advertencia de privacidad antes de descargar el paquete para compartirlo manualmente.
- Guardar recomendaciones manuales sólo en la base SQLite del workspace privado. La base conserva identificadores técnicos, texto ingresado por el usuario, estados y timestamps; no copia imágenes, XMP, EXIF, GPS ni rutas absolutas de la sesión.
- Tratar el texto libre de recomendaciones como dato privado: puede contener observaciones sensibles aunque la aplicación no las infiera ni las transmita.

## Retención y eliminación

La política concreta está pendiente. Como base:

- RAW y originales permanecen bajo la política existente del fotógrafo.
- Miniaturas, proxies y hojas de contacto deben poder regenerarse; su eliminación desde la aplicación queda fuera de la Fase 0.
- En la Fase 0 no habrá eliminación desde la aplicación; proxies y hojas de contacto sólo podrán limpiarse manualmente fuera de ella.
- Snapshots XMP deben retenerse mientras exista una propuesta aplicada o la necesidad de restauración.
- Los registros SQLite deben poder desvincularse de rutas que ya no existen sin intentar borrar las fuentes.

## Decisiones pendientes

- Datos mínimos necesarios para identificar y contactar modelos.
- Necesidad de cifrado del workspace o de campos particulares.
- Retención por tipo de sesión y mecanismo de borrado verificable.
- Contenido permitido en propuestas y hojas de contacto compartibles.
- Tratamiento de GPS, menores de edad y material especialmente sensible.
- Alcance de autenticación local si el equipo tiene múltiples usuarios.
- Política futura de limpieza explícita y verificable de proxies y hojas de contacto.
- Condiciones para una posible integración futura mediante API, sujetas a consentimiento, credenciales y controles separados.

Este documento orienta el diseño técnico y no reemplaza asesoramiento legal ni los consentimientos aplicables.
