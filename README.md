# photo-session-workflow

Proyecto local para diseñar y, más adelante, implementar un flujo de producción fotográfica integrado con Adobe Lightroom Classic.

## Estado

El repositorio contiene únicamente documentación. La Fase 0 está definida y pendiente de implementación; todavía no hay una aplicación Flask, dependencias instaladas, esquema SQLite ni código funcional.

## Objetivo

La visión futura es centralizar tres partes del trabajo fotográfico:

- preproducción y propuesta creativa;
- propuesta interna y presentación para la modelo;
- posproducción asistida e integrada con Lightroom Classic.

El objetivo inmediato está recortado a la **Fase 0 de posproducción**: trabajar localmente con fotografías ya seleccionadas y editadas parcialmente en Lightroom Classic, leer desde XMP las estrellas correspondientes al último estado guardado con `Ctrl+S`, generar proxies y hojas de contacto, confirmar una selección reducida y preparar únicamente esa selección para análisis visual asistido. Lightroom Classic seguirá siendo el editor principal.

La Fase 0 es estrictamente de lectura respecto del material fotográfico y de Lightroom. No modifica XMP, RAW, JPG, TIFF ni DNG; no abre ni escribe catálogos `.lrcat`; no restaura versiones y no elimina archivos.

## Principios

- Los RAW y JPG originales son de solo lectura.
- Los sidecars XMP y archivos ACR auxiliares son de solo lectura en la Fase 0.
- El código y su base local no contienen catálogos, fotos reales ni archivos privados de modelos.
- Los proxies y hojas de contacto se guardan en un workspace privado fuera del repositorio.
- La aplicación genera un paquete local de revisión; sólo el usuario decide si lo carga manualmente en ChatGPT u otro servicio.
- La aplicación no controla ChatGPT, no utiliza su API, no almacena credenciales y no transmite archivos automáticamente.
- Toda sugerencia creativa o técnica requiere confirmación del usuario y nunca se aplica automáticamente.
- La aplicación será local y orientada a Windows.

## Documentación

- [`docs/requirements.md`](docs/requirements.md): requisitos, supuestos y alcance del MVP.
- [`docs/design.md`](docs/design.md): arquitectura y modelo conceptual.
- [`docs/workflow.md`](docs/workflow.md): flujo operativo propuesto.
- [`docs/privacy.md`](docs/privacy.md): límites y tratamiento de datos privados.
- [`docs/lightroom-integration.md`](docs/lightroom-integration.md): estrategia XMP/ACR y límites con Lightroom.
- [`docs/phase-0-postproduction.md`](docs/phase-0-postproduction.md): alcance cerrado, tareas y criterios de aceptación de la Fase 0.
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

Antes de implementar se debe aprobar el plan de `docs/phase-0-postproduction.md`. Las preguntas restantes están documentadas como decisiones futuras y no bloquean la Fase 0.
