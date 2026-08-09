# photo-session-workflow

Proyecto local para diseñar y, más adelante, implementar un flujo de producción fotográfica integrado con Adobe Lightroom Classic.

## Estado

El repositorio contiene únicamente documentación inicial. Todavía no hay una aplicación Flask, dependencias instaladas, esquema SQLite ni código funcional.

## Objetivo

Centralizar dos partes del trabajo fotográfico:

- la preproducción de sesiones (estilo, modelo, locación, vestuario, referencias y planes);
- el análisis no destructivo de carpetas RAW y sidecars XMP para revisión, agrupación, hojas de contacto y selección.

La integración del MVP se limita a archivos del sistema y sidecars XMP/ACR. No se modificará directamente ningún catálogo `.lrcat`.

## Principios

- Los RAW y JPG originales son de solo lectura.
- Todo XMP original se conserva; las propuestas se escriben en un área separada.
- El código y su base local no contienen catálogos, fotos reales ni archivos privados de modelos.
- Toda escritura debe ser explícita, trazable y reversible.
- La aplicación será local y orientada a Windows.

## Documentación

- [`docs/requirements.md`](docs/requirements.md): requisitos, supuestos y alcance del MVP.
- [`docs/design.md`](docs/design.md): arquitectura y modelo conceptual.
- [`docs/workflow.md`](docs/workflow.md): flujo operativo propuesto.
- [`docs/privacy.md`](docs/privacy.md): límites y tratamiento de datos privados.
- [`docs/lightroom-integration.md`](docs/lightroom-integration.md): estrategia XMP/ACR y límites con Lightroom.
- [`config.example.yaml`](config.example.yaml): configuración ilustrativa sin datos reales.

## Estructura inicial

```text
photo-session-workflow/
├── app/                 # Reservado para una implementación futura
├── docs/
├── templates/           # Reservado para plantillas HTML futuras
├── tests/               # Reservado para pruebas futuras
├── .gitignore
├── AGENTS.md
├── README.md
└── config.example.yaml
```

## Próxima revisión

Antes de implementar se deben validar las decisiones pendientes de `docs/requirements.md`, especialmente el método de generación de miniaturas, la política de escritura XMP y el límite de datos personales almacenados.
