# UADE Teams Downloader

Pipeline automatico que descarga material de Microsoft Teams, organiza en carpetas, transcribe grabaciones con Whisper y genera resumenes inteligentes con IA.

**Cross-platform:** Funciona en macOS, Windows y Linux.

## Pipeline

```
Trigger (launchd / Task Scheduler / manual)
    └── run-pipeline.sh / run-pipeline.bat
         ├── 1. downloader.py    → descarga de Teams/SharePoint
         ├── 2. organizer.py     → clasifica y mueve a carpetas
         ├── 3. transcriber.py   → transcribe (Whisper) + resume (LLM)
         │      ├── genera resumen con contexto (slides + cronograma)
         │      ├── extrae tareas a tareas.md
         │      └── detecta calidad de audio
         └── 4. status.py        → reporte del estado
```

## Setup rapido

```bash
python setup.py
```

El setup interactivo guia paso a paso: instala dependencias, configura el backend de transcripcion segun tu SO, y pide API keys si corresponde.

### Setup manual

```bash
git clone <repo-url>
cd uade-teams-downloader
python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate.bat       # Windows

pip install -r requirements.txt
playwright install chromium

# Transcripcion — elegir UNO:
pip install -r requirements-mlx.txt       # macOS Apple Silicon (GPU Metal)
pip install -r requirements-whisper.txt   # Windows/Linux (GPU CUDA o CPU)

# LLM para resumenes — elegir UNO:
# Opcion A: Instalar Claude Code (https://claude.ai/code)
# Opcion B: Gemini (gratis):
pip install -r requirements-gemini.txt
cp .env.template .env
# Editar .env y agregar GEMINI_API_KEY
# Opcion C: Ollama (https://ollama.ai) + ollama pull llama3
```

### Login en Teams

```bash
python downloader.py --visible     # Abre browser, loguearse en Teams
```

La sesion se guarda en `data/session/` y dura ~30 dias. Si expira, el sistema reabre el browser automaticamente.

## Configuracion

El sistema auto-detecta el entorno. Sin configuracion, usa los defaults. Para personalizar, copiar `.env.template` a `.env`:

| Variable | Default | Descripcion |
|----------|---------|-------------|
| `UADE_BASE_DIR` | `~/UADE/4to cuatrimestre` | Carpeta base de materias |
| `WHISPER_BACKEND` | auto-detecta | `mlx` (macOS ARM) o `openai-whisper` |
| `LLM_PROVIDER` | auto-detecta | `claude-cli`, `gemini`, `ollama` |
| `GEMINI_API_KEY` | — | API key de Google AI Studio (gratis) |
| `FOLDER_*` | `01_Material_de_Clase`, etc. | Nombres de carpetas personalizables |

## Estructura de destino

```
~/UADE/4to cuatrimestre/Materia_X/
├── 01_Material_de_Clase/    ← slides, PDFs (CLASE_XX_...)
├── 02_Apuntes_Personales/   ← resumenes generados (GRAB_XX_resumen.md)
├── 03_Trabajos_Practicos/   ← ejercicios, TPs (TP_XX_...)
├── 04_Evaluaciones/         ← parciales, finales
├── 05_Grabaciones/          ← videos + transcripciones (GRAB_XX_...)
├── 06_Material_Extra/       ← cronogramas, bibliografia
├── teams_material/          ← staging (se limpia despues)
└── tareas.md                ← tareas consolidadas de todas las clases
```

Las carpetas se crean automaticamente en la primera ejecucion.

## Uso

```bash
# Pipeline completo
./run-pipeline.sh              # macOS/Linux
run-pipeline.bat               # Windows

# Scripts individuales
python downloader.py                  # Descargar todo
python downloader.py --team 568898    # Solo una materia
python organizer.py                   # Organizar archivos
python organizer.py --dry-run         # Ver que haria sin mover
python transcriber.py                 # Transcribir + resumir
python transcriber.py --no-summary    # Solo transcribir (sin LLM)
python transcriber.py --file x.mp4    # Solo un archivo
python status.py                      # Resumen del pipeline
python status.py --mp4                # Ciclo de vida de grabaciones
```

## Features

- **Auto-deteccion de entorno:** Detecta SO, GPU, y LLM disponible sin configuracion manual
- **Idempotencia:** SQLite trackea el estado de cada archivo. Correr multiples veces es seguro
- **Crash-safety:** WAL mode en SQLite + archivos temporales `.downloading`
- **Deduplicacion:** Detecta archivos espejados de SharePoint por nombre + tamaño
- **Resumenes con contexto:** Incluye slides, cronograma y resumen anterior en el prompt
- **Deteccion de cambios:** Si hay slides nuevos para una clase ya resumida, regenera el resumen
- **Calidad de audio:** Detecta transcripciones de baja calidad y agrega advertencia al resumen
- **Tareas consolidadas:** Extrae tareas de todos los resumenes a un `tareas.md` por materia
- **Graceful sin LLM:** Sin LLM configurado, descarga y transcribe igual (sin resumenes)
- **Login automatico:** Si la sesion expira, reabre el browser para login en vez de fallar

## Seguridad

- **Credenciales:** Nunca se guardan passwords. La sesion de Teams usa cookies del browser (Playwright persistent context) almacenadas en `data/session/` (gitignored)
- **API keys:** Se leen de variables de entorno o `.env` (gitignored). Nunca estan en el codigo
- **Transcripcion local:** Whisper corre 100% local. El audio no se envia a ningun servidor
- **Resumenes:** Se envian a la API del LLM elegido (Claude/Gemini). No enviar material sensible si eso es un problema

## Troubleshooting

| Problema | Solucion |
|----------|----------|
| Sesion expirada | El sistema reabre el browser automaticamente. Si no, correr `python downloader.py --visible` |
| Sin LLM | El pipeline sigue (descarga + transcripcion). Configurar Gemini API key gratis para resumenes |
| Transcripcion lenta | Sin GPU tarda ~30-60 min por clase. Con GPU CUDA/Metal ~5 min |
| Resumen pobre | Verificar que las slides esten en `01_Material_de_Clase/` con prefijo `CLASE_XX_` |
| Organizer clasifica mal | Correr con `--dry-run`. Los ambiguos se clasifican con LLM |

## Dependencias

| Paquete | Rol | Plataforma |
|---------|-----|-----------|
| playwright | Auth de Teams via browser | Todas |
| requests | API REST de SharePoint | Todas |
| mlx-whisper | Transcripcion GPU Metal | macOS Apple Silicon |
| openai-whisper | Transcripcion GPU CUDA / CPU | Windows/Linux |
| google-generativeai | Resumenes con Gemini | Todas (opcional) |
| pypdf, python-pptx | Extraccion de texto de slides | Todas |
| python-dotenv | Configuracion desde .env | Todas |
