# UADE Teams Downloader

Pipeline automático: descarga material de Teams, organiza en carpetas, transcribe grabaciones y genera resúmenes.

## Pipeline

```
launchd (horarios programados)
    └── run-pipeline.sh
         ├── 1. downloader.py    → baja todo a teams_material/
         ├── 2. organizer.py     → mueve a 01_-06_ con nomenclatura
         └── 3. transcriber.py   → transcribe mp4 + resumen con Claude
```

## Estructura del repo

```
downloader.py                          # Descarga de Teams/SharePoint
organizer.py                           # Clasifica y mueve a 01_-06_
transcriber.py                         # Transcripción (mlx-whisper) + resúmenes (claude -p)
run-pipeline.sh                        # Orquestador para launchd
run-downloader.sh                      # Wrapper legacy (solo descarga)
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
└── teams_material/          ← dump crudo de SharePoint (staging)
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

Si la Mac estaba dormida, launchd ejecuta al despertar.

## Uso manual

```bash
source .venv/bin/activate

# Pipeline completo
./run-pipeline.sh

# Scripts individuales
python3 downloader.py                  # Descargar todo
python3 downloader.py --team 568898    # Solo una materia
python3 organizer.py                   # Organizar archivos
python3 organizer.py --dry-run         # Ver qué haría sin mover
python3 transcriber.py                 # Transcribir + resumir
python3 transcriber.py --no-summary    # Solo transcribir
python3 transcriber.py --file x.mp4    # Solo un archivo
```

## Auth y sesión

- La sesión de Teams/SharePoint dura ~30 días.
- Si expira, el pipeline lo detecta y envía una notificación de macOS.
- Para re-loguearse: `python3 downloader.py --visible`
- El pipeline sigue corriendo organizer + transcriber aunque falle la descarga.

## Verificar

```bash
launchctl list | grep uade                     # Agent cargado
launchctl start com.andreiveis.uade-downloader # Forzar ejecución
ls -lt data/logs/                              # Logs recientes
sqlite3 data/downloads.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5;"
sqlite3 data/downloads.db "SELECT * FROM organized ORDER BY rowid DESC LIMIT 10;"
sqlite3 data/downloads.db "SELECT * FROM transcriptions;"
```

## Desinstalar

```bash
launchctl unload ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
rm ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
```

## Troubleshooting

- **Notificación "Sesión expirada"**: Correr `python3 downloader.py --visible`.
- **Logs vacíos**: Verificar dependencias (`pip install -r requirements.txt`).
- **launchd no corre**: Re-cargar el plist con `launchctl load`.
- **Organizer clasifica mal**: Correr con `--dry-run` primero. Los ambiguos se clasifican con `claude -p`.
- **Transcripción lenta**: mlx-whisper usa GPU de Apple Silicon. ~10 min por hora de clase con modelo medium.
