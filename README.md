# photo-session-workflow

Proyecto local para diseñar y, más adelante, implementar un flujo de producción fotográfica integrado con Adobe Lightroom Classic.

## Estado

P0-01 a P0-05 de la Fase 0 están implementados: fronteras de rutas, fixtures sintéticos, inventario, relaciones lógicas y lectura EXIF controlada. Todavía no hay aplicación Flask, SQLite, lectura de estrellas XMP, generación de proxies ni procesamiento de material real.

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
- [`config.example.json`](config.example.json): configuración de rutas ilustrativa sin datos reales.

## Configuración local

Copiar `config.example.json` como `config.local.json` y reemplazar los valores por rutas absolutas existentes:

- `session_root`: carpeta externa de sesión, accesible sólo mediante `SessionReader`;
- `workspace_root`: workspace privado con capacidad de lectura/escritura;
- `repository_root`: raíz protegida de este repositorio.
- `exiftool.executable`: ruta absoluta a una instalación local de `exiftool.exe`, fuera de sesión, workspace y repositorio;
- `exiftool.timeout_seconds`: timeout conservador por proceso;
- `exiftool.max_output_bytes`: límite de captura por stream.

`config.local.json` está ignorado por Git. Las tres raíces deben ser disjuntas: la validación rechaza igualdad, anidamiento en cualquier dirección y symlinks, junctions o reparse points detectables.

## ExifTool para P0-05

ExifTool es una dependencia externa futura que debe instalar y administrar explícitamente el usuario. La aplicación no lo descarga, instala ni versiona. Para verificar una instalación local desde PowerShell:

```powershell
& 'X:\ruta\local\exiftool.exe' -ver
```

La aplicación sólo ejecuta comandos de lectura con tags fijos, JSON y valores numéricos. No acepta flags configurables. Las pruebas normales usan runners falsos y no requieren ExifTool; la prueba real de versión permanece omitida salvo que se definan `PHOTO_SESSION_EXIFTOOL_INTEGRATION=1` y `PHOTO_SESSION_EXIFTOOL_PATH`.

## Pruebas de P0-01 a P0-05

No se requieren dependencias externas. En Windows, con Python 3.11 o posterior:

```powershell
py -3 -m unittest discover -s tests -v
```

Si `python` ya está disponible en `PATH`:

```powershell
python -m unittest discover -s tests -v
```

Los tests generan en directorios temporales archivos de texto con extensiones `.NEF`, `.jpg`, `.xmp` y `.acr`. No son fotografías ni validan decodificación RAW/JPEG; sólo representan nombres, casos sintéticos y metadatos del filesystem.

Las pruebas de P0-03 verifican recorrido recursivo y no recursivo, extensiones sin distinción de mayúsculas, orden estable, rutas relativas, aislamiento de errores, rechazo de datos Lightroom y enlaces detectables, volumen superior a 200 fotografías simuladas y ausencia de lecturas de contenido o escrituras. Las pruebas de symlinks se omiten cuando Windows no concede el privilegio necesario; la detección de reparse points también tiene cobertura determinista independiente.

## Estructura inicial

```text
photo-session-workflow/
├── app/                 # Reservado para Flask; permanece vacío
├── docs/
├── photo_session_workflow/
│   ├── config.py        # Carga y validación de configuración local
│   ├── exif.py          # Selección y lectura EXIF filtrada mediante ExifTool
│   ├── inventory.py     # Inventario inmutable de metadatos del filesystem
│   ├── paths.py         # Fronteras y capacidades de filesystem
│   └── relations.py     # Relaciones lógicas entre entradas admitidas
├── templates/           # Reservado para plantillas HTML futuras
├── tests/               # unittest y generador de fixtures temporales
├── .gitignore
├── AGENTS.md
├── README.md
└── config.example.json
```

## Próxima revisión

La implementación debe detenerse al completar P0-05. P0-06 y las tareas posteriores requieren una autorización nueva. Las preguntas restantes están documentadas como decisiones futuras y no bloquean estas bases.
