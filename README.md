# Reportabilidad — reporte de turno

Genera el reporte de turno (STG Chile / CCU) a partir de los datos del sistema:
resumen del turno, pasillos y equipos no devueltos, con PDF A4 listo para enviar.

## Uso

```bash
python3 app.py          # http://localhost:12000
```

| Ruta | Qué hace |
|---|---|
| `/` | Bandeja para subir las capturas del turno |
| `/editor` | Formulario con vista previa en vivo |
| `/historial` | Reportes guardados (ver, PDF, editar) |
| `/reporte?id=<id>` | Reporte final |
| `/reporte.pdf?id=<id>` | PDF A4 generado con Chromium |

Requisitos: Python 3.9+ y Chromium (`/usr/bin/chromium`) para el PDF. Sin dependencias externas.

## Cargar los equipos no devueltos

En el editor puedes:

- pegar la tabla copiada desde Excel/Sheets (TSV),
- subir un CSV, o
- agregar filas a mano.

Las columnas se detectan por el encabezado (`serie`, `codigo`, `nombre`, `observacion`,
`fecha`, `hora`, `empresa`) o, si no hay encabezado, por el contenido de cada columna.

## Estructura

```
app.py                     servidor (stdlib) + generación de PDF
editor.html                formulario y vista previa
reporte.html               plantilla del reporte (fuente Inter embebida)
reportes/<id>.json         datos de cada reporte guardado
informeSTG.png             captura de origen (resumen del turno)
noentrega.png              captura de origen (equipos no devueltos)
```

## Datos

Cada reporte queda en `reportes/<fecha>-turno-<x>.json`, así que se puede versionar y
regenerar el PDF cuando haga falta.
