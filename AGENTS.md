# AGENTS.md

## Alcance del repositorio

Estas instrucciones aplican a todo el proyecto.

## Estado actual

La implementación está autorizada exclusivamente para P0-01 y P0-02:

- contrato de sesión, configuración y fronteras de rutas;
- fixtures sintéticos generados durante las pruebas.

Hasta una nueva autorización:

- no avanzar a P0-03 ni implementar descubrimiento de fotografías;
- no inicializar Flask ni SQLite;
- no instalar dependencias sin justificación previa;
- no procesar fotografías reales;
- no abrir, copiar ni modificar catálogos Lightroom.

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

## Criterios para cambios futuros

- Actualizar la documentación cuando cambie una decisión de diseño.
- Añadir pruebas con fixtures mínimos y sintéticos antes de procesar sesiones reales.
- Verificar en copias de prueba cualquier comportamiento dependiente de Lightroom Classic o Adobe Camera Raw.
- Evitar ampliar el MVP sin registrar la decisión y su impacto en privacidad y recuperación.
- No implementar funciones fuera de `docs/phase-0-postproduction.md` mientras la Fase 0 sea el alcance activo.
