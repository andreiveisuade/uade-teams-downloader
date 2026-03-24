# UADE Teams Downloader

Pipeline automático: descarga material de Teams, organiza en carpetas, transcribe grabaciones y genera resúmenes inteligentes para estudio.

## Pipeline

```
launchd (horarios programados)
    └── run-pipeline.sh (caffeinate + spinner)
         ├── 1. downloader.py    → baja de Teams/SharePoint a teams_material/
         ├── 2. organizer.py     → mueve a 01_-06_ con nomenclatura estándar
         ├── 3. transcriber.py   → transcribe mp4 (mlx-whisper) + resumen (claude -p sonnet)
         └── 4. status.py        → reporte del ciclo de vida de archivos
```

Si la Mac estaba dormida, launchd ejecuta al despertar. El pipeline bloquea idle sleep con `caffeinate` durante la ejecución.

## Estructura del repo

```
downloader.py                          # Descarga de Teams/SharePoint
organizer.py                           # Clasifica y mueve a 01_-06_
transcriber.py                         # Transcripción + resúmenes inteligentes
status.py                              # Vista unificada del ciclo de vida
run-pipeline.sh                        # Orquestador (caffeinate, spinner, tee al log)
uade-login.sh                          # Re-login de Teams (abre browser)
com.andreiveis.uade-downloader.plist   # launchd agent
requirements.txt                       # Dependencias Python
data/                                  # (gitignored)
├── downloads.db                       # SQLite: downloads, runs, organized, transcriptions
├── session/                           # Browser context persistente (Playwright)
└── logs/                              # Logs de ejecuciones automáticas
```

## Estructura de destino (por materia)

```
~/UADE/4to cuatrimestre/Materia_X/
├── 01_Material_de_Clase/    ← slides, PDFs de clase     (CLASE_XX_...)
├── 02_Apuntes_Personales/   ← resúmenes generados       (GRAB_XX_resumen.md)
├── 03_Trabajos_Practicos/   ← ejercicios, TPs           (TP_XX_...)
├── 04_Evaluaciones/         ← parciales, finales         (EVAL_...)
├── 05_Grabaciones/          ← videos + transcripciones   (GRAB_XX_...)
├── 06_Material_Extra/       ← cronogramas, bibliografía
└── teams_material/          ← staging (se limpia después de organizar)
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Login inicial

```bash
python3 downloader.py --visible
```

Se abre Chromium. Loguearse en Teams. La sesión queda en `data/session/`.

### Instalar automatización

```bash
cp com.andreiveis.uade-downloader.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
```

## Horarios automáticos

| Materia                      | Prefijo | Clase termina | Pipeline corre |
|------------------------------|---------|---------------|----------------|
| IA Aplicada                  | 568898  | Lun 22:45     | Lun 23:45      |
| PDS                          | 558193  | Mar 11:45     | Mar 12:45      |
| Desarrollo de Aplicaciones I | 562914  | Jue 11:45     | Jue 18:30      |
| Ingeniería de Datos II       | 561218  | Jue 17:30     | Jue 18:30      |

## Uso manual

```bash
source .venv/bin/activate

# Pipeline completo (con spinner y colores en terminal)
./run-pipeline.sh

# Scripts individuales
python3 downloader.py                  # Descargar todo
python3 downloader.py --team 568898    # Solo una materia
python3 organizer.py                   # Organizar archivos
python3 organizer.py --dry-run         # Ver qué haría sin mover
python3 transcriber.py                 # Transcribir + resumir
python3 transcriber.py --no-summary    # Solo transcribir
python3 transcriber.py --file x.mp4    # Solo un archivo
python3 status.py                      # Resumen del pipeline
python3 status.py --pending            # Qué falta procesar
python3 status.py --mp4                # Ciclo de vida de grabaciones
python3 status.py --detail             # Detalle por materia
```

## Resúmenes inteligentes

Cada grabación genera un resumen en `02_Apuntes_Personales/` con formato Obsidian:

- **Modelo**: Claude Sonnet via `claude -p`
- **Contexto por clase**: extrae texto de las slides de esa clase (`CLASE_XX_*`), el cronograma de la materia, y el resumen de la clase anterior
- **Extracción**: PDFs (pypdf), PPTXs (python-pptx), DOCX
- **Formato**: temas, conceptos para examen, citas del profe, correspondencia con slides, tareas con `- [ ] tarea 📅 fecha`
- **Paralelismo**: el resumen de la clase N-1 se genera en background mientras se transcribe la clase N (GPU + red no compiten)

## Auth y sesión

- La sesión de Teams/SharePoint dura ~30 días.
- Si expira, el pipeline lo detecta (exit code 2), envía notificación de macOS, y sigue con los pasos 2-4.
- Para re-loguearse:
  ```bash
  ./uade-login.sh
  ```
- Se abre Chromium, te logueás en Teams, y la sesión queda guardada.

## Verificar

```bash
launchctl list | grep uade                     # Agent cargado
launchctl start com.andreiveis.uade-downloader # Forzar ejecución
ls -lt data/logs/                              # Logs recientes
python3 status.py                              # Estado del pipeline
python3 status.py --mp4                        # Ciclo de vida de grabaciones
```

## Desinstalar

```bash
launchctl unload ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
rm ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
```

## Troubleshooting

- **Notificación "Sesión expirada"**: Correr `./uade-login.sh`.
- **Logs vacíos**: Verificar dependencias (`pip install -r requirements.txt`).
- **launchd no corre**: Re-cargar el plist con `launchctl load`.
- **Organizer clasifica mal**: Correr con `--dry-run` primero. Los ambiguos se clasifican con `claude -p`.
- **Transcripción lenta**: mlx-whisper usa GPU de Apple Silicon. ~10 min por hora de clase con modelo medium.
- **Mac se duerme durante el pipeline**: No debería — `caffeinate -i` bloquea idle sleep. Se libera al terminar.
- **claude no disponible**: El pipeline detecta si `claude` CLI no está en PATH y corre transcripción sin resúmenes.
- **Resumen pobre**: Verificar que las slides de esa clase estén en `01_Material_de_Clase/` con prefijo `CLASE_XX_`. Sin slides, el resumen se basa solo en la transcripción.

## Dependencias

- `playwright` — Automatización de browser para auth de Teams
- `requests` — API REST de SharePoint
- `mlx-whisper` — Transcripción local en Apple Silicon
- `pypdf` — Extracción de texto de PDFs
- `python-pptx` — Extracción de texto de presentaciones
- `claude` CLI — Generación de resúmenes (Claude Code, plan Pro/Max)
