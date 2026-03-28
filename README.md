# UADE Teams Downloader

Pipeline automatico que descarga material de Microsoft Teams, organiza en carpetas, transcribe grabaciones con Whisper y genera resumenes con IA.

Funciona en macOS, Windows y Linux.

## Que hace

1. **Descarga** grabaciones, slides y material de Teams/SharePoint
2. **Organiza** los archivos en carpetas estandarizadas por materia
3. **Transcribe** las grabaciones de clase con Whisper (100% local)
4. **Genera resumenes** estructurados con IA (temas, conceptos clave, citas del profesor)
5. **Extrae tareas** y las consolida en un archivo `tareas.md` por materia

```
Teams/SharePoint
    → downloader.py (descarga)
    → organizer.py (clasifica en carpetas)
    → transcriber.py (Whisper + LLM)
    → status.py (reporte)
```

## Instalacion

### Opcion A: Setup guiado (recomendado)

```bash
git clone https://github.com/andreiveisuade/uade-teams-downloader.git
cd uade-teams-downloader
python setup.py
```

El setup pregunta paso a paso: carpeta destino, API key para resumenes, IDs de equipos de Teams, y login.

### Opcion B: Instalacion manual

**1. Clonar y crear entorno virtual:**

```bash
git clone https://github.com/andreiveisuade/uade-teams-downloader.git
cd uade-teams-downloader
python -m venv .venv
```

**2. Activar el entorno virtual:**

```bash
# macOS / Linux:
source .venv/bin/activate

# Windows:
.venv\Scripts\activate.bat
```

**3. Instalar dependencias base:**

```bash
pip install -r requirements.txt
playwright install chromium
```

**4. Instalar Whisper (transcripcion):**

```bash
# macOS Apple Silicon:
pip install -r requirements-mlx.txt

# Windows o Linux:
pip install -r requirements-whisper.txt
```

**5. Configurar IA para resumenes (elegir una opcion):**

| Opcion | Comando | Costo |
|--------|---------|-------|
| Google Gemini | `pip install -r requirements-gemini.txt` | Gratis |
| Claude Code | Instalar desde https://claude.ai/code | Suscripcion |
| Ollama | Instalar desde https://ollama.ai | Gratis (local) |

Para Gemini, obtener API key gratis en https://aistudio.google.com y agregarla al archivo `.env`:

```bash
cp .env.template .env
# Editar .env y poner la API key en GEMINI_API_KEY=
```

Sin LLM configurado, el sistema descarga y transcribe pero no genera resumenes.

**6. Configurar equipos de Teams:**

Agregar los IDs de tus equipos al archivo `.env`:

```
TEAM_PREFIXES=568898,561218,558193
```

Para encontrar los IDs: abrir Teams en el browser, entrar a un equipo, y buscar el numero en la URL (`...Section_XXXXXX/...`).

**7. Login en Teams (primera vez):**

```bash
python downloader.py --visible
```

Se abre un browser. Loguearse con la cuenta de UADE. La sesion se guarda y dura ~30 dias. Si expira, el sistema reabre el browser automaticamente.

## Uso diario

```bash
# Activar el entorno:
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate.bat       # Windows

# Correr el pipeline completo:
./run-pipeline.sh                  # macOS/Linux
run-pipeline.bat                   # Windows
```

El pipeline descarga archivos nuevos, los organiza, transcribe grabaciones pendientes y genera resumenes. Correr multiples veces es seguro: solo procesa lo nuevo.

### Comandos individuales

```bash
python downloader.py                  # Descargar todo
python downloader.py --team 568898    # Solo una materia
python organizer.py                   # Organizar archivos
python organizer.py --dry-run         # Ver que haria sin mover
python transcriber.py                 # Transcribir + resumir
python transcriber.py --no-summary    # Solo transcribir
python transcriber.py --file video.mp4  # Solo un archivo
python status.py                      # Estado general
python status.py --mp4                # Ciclo de vida de grabaciones
python status.py --pending            # Que falta procesar
```

## Estructura de carpetas

Al correr el pipeline, cada materia se organiza asi (las carpetas se crean solas):

```
~/UADE/4to cuatrimestre/Nombre_Materia/
├── 01_Material_de_Clase/    slides, PDFs de clase
├── 02_Apuntes_Personales/   resumenes generados por el pipeline
├── 03_Trabajos_Practicos/   ejercicios y TPs
├── 04_Evaluaciones/         parciales y finales
├── 05_Grabaciones/          videos de clase + transcripciones .txt
├── 06_Material_Extra/       cronogramas, bibliografia
└── tareas.md                tareas consolidadas de todas las clases
```

## Configuracion

Todo se configura en el archivo `.env` (copiar desde `.env.template`). Sin `.env`, el sistema usa defaults y auto-detecta lo que puede.

| Variable | Para que sirve | Default |
|----------|---------------|---------|
| `UADE_BASE_DIR` | Carpeta donde estan las materias | `~/UADE/4to cuatrimestre` |
| `TEAM_PREFIXES` | IDs de equipos de Teams (separados por coma) | — |
| `GEMINI_API_KEY` | API key de Google AI Studio para resumenes | — |
| `WHISPER_BACKEND` | Forzar backend: `mlx` o `openai-whisper` | Auto-detecta |
| `LLM_PROVIDER` | Forzar LLM: `claude-cli`, `gemini`, `ollama` | Auto-detecta |

## Seguridad

- Las credenciales de Teams nunca se guardan como texto. La sesion usa cookies del browser almacenadas localmente (gitignored).
- Las API keys se leen del archivo `.env` (gitignored). No estan en el codigo.
- Whisper corre local. El audio no se envia a ningun servidor externo.
- Los resumenes se envian a la API del LLM elegido (Claude, Gemini, u Ollama local).

## Troubleshooting

| Problema | Solucion |
|----------|----------|
| "Sesion expirada" | El sistema reabre el browser solo. Si no, correr `python downloader.py --visible` |
| No genera resumenes | Verificar que hay un LLM configurado (`python -c "import config; print(config.detect_llm_provider())"`) |
| Transcripcion lenta | Sin GPU tarda ~30-60 min por clase. Con GPU (CUDA o Metal) ~5 min |
| Resumen sin contexto | Verificar que las slides esten en `01_Material_de_Clase/` con prefijo `CLASE_XX_` |
