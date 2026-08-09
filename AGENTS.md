# AGENTS.md

## Alcance del repositorio

Estas instrucciones aplican a todo el proyecto.

## Estado actual

El proyecto está en fase de diseño documental. Hasta que el usuario apruebe el diseño:

- no inicializar Flask;
- no instalar dependencias;
- no crear código funcional ni esquemas de base de datos ejecutables;
- no procesar fotografías reales;
- no abrir, copiar ni modificar catálogos Lightroom.

## Reglas permanentes de seguridad de datos

- Tratar RAW, JPG originales, catálogos `.lrcat` y sidecars XMP existentes como entradas de solo lectura.
- Nunca modificar ni sobrescribir un RAW.
- Nunca editar directamente un catálogo `.lrcat`.
- Guardar miniaturas, hojas de contacto, índices y propuestas XMP únicamente en rutas de trabajo configuradas fuera de las fuentes.
- Antes de proponer escritura junto a una fotografía, exigir una operación explícita y conservar una copia versionada del sidecar original.
- No incluir fotografías reales, catálogos, credenciales, datos personales ni archivos privados de modelos en Git, fixtures o logs.
- Usar datos sintéticos en pruebas futuras.

## Límites de arquitectura

- Stack previsto: Python, Flask, SQLite, HTML, CSS y JavaScript vanilla.
- Ejecución local en Windows; no asumir servicios cloud.
- Mantener separadas las capas de dominio, persistencia, análisis de medios, integración XMP y presentación web.
- Las rutas externas deben venir de configuración local ignorada por Git; nunca codificarlas en el código.
- Toda operación futura que escriba archivos debe ser idempotente cuando sea posible, auditable y reversible.

## Criterios para cambios futuros

- Actualizar la documentación cuando cambie una decisión de diseño.
- Añadir pruebas con fixtures mínimos y sintéticos antes de activar escritura XMP.
- Verificar en copias de prueba cualquier comportamiento dependiente de Lightroom Classic o Adobe Camera Raw.
- Evitar ampliar el MVP sin registrar la decisión y su impacto en privacidad y recuperación.
