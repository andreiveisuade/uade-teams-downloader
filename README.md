# UADE Teams Downloader

Descarga automaticamente el material de tus materias de Teams: grabaciones, slides, PDFs. Los organiza en carpetas, transcribe las clases con Whisper (local, no sube nada) y genera resumenes con IA.

## Guia de instalacion — Windows

### Paso 1: Instalar Git

Git es lo que te permite descargar este programa.

1. Ir a https://gitforwindows.org
2. Descargar e instalar con las opciones por defecto (Next, Next, Next...)

### Paso 2: Instalar Python

1. Ir a https://www.python.org/downloads/
2. Descargar e instalar
3. **MUY IMPORTANTE:** en la primera pantalla del instalador, marcar la casilla **"Add Python to PATH"** antes de hacer click en Install

### Paso 3: Descargar este programa

Abrir una terminal (buscar "cmd" en el menu Inicio) y escribir:

```
git clone https://github.com/andreiveisuade/uade-teams-downloader.git
```

### Paso 4: Correr el setup

En el Explorador de archivos, ir a la carpeta `uade-teams-downloader` que se acaba de crear, y **doble click en `setup.bat`**.

El setup te va a guiar paso a paso:
- Te pregunta donde guardar los archivos (Enter para aceptar el default)
- Instala las dependencias automaticamente (tarda unos minutos, vas a ver puntitos de progreso)
- Te pide una API key de Google para los resumenes (es gratis, te explica como obtenerla)
- Te pide los IDs de tus equipos de Teams (te explica donde encontrarlos)
- Te pide loguearte en Teams en un browser que se abre solo

### Paso 5: Uso diario

Cada vez que quieras descargar material nuevo, **doble click en `run-pipeline.bat`**.

Se abre una ventana que muestra el progreso. Cuando termina, tus archivos estan organizados en la carpeta que elegiste.

---

## Guia de instalacion — macOS

### Paso 1: Instalar herramientas

Abrir la Terminal y correr:

```bash
xcode-select --install
```

Esto instala Git y herramientas de desarrollo. Si ya las tenes, te va a decir.

### Paso 2: Verificar Python

macOS viene con Python. Verificar que es 3.10+:

```bash
python3 --version
```

Si es menor a 3.10: `brew install python`.

### Paso 3: Descargar este programa

```bash
git clone https://github.com/andreiveisuade/uade-teams-downloader.git
cd uade-teams-downloader
```

### Paso 4: Correr el setup

```bash
python3 setup.py
```

Te guia paso a paso (igual que en Windows).

### Paso 5: Uso diario

```bash
./run-pipeline.sh
```

---

## Que hace el pipeline

Cada vez que lo corres:

1. **Descarga** archivos nuevos de Teams (grabaciones, slides, PDFs)
2. **Organiza** todo en carpetas por materia
3. **Transcribe** las grabaciones de clase (100% local, no sube audio)
4. **Genera resumenes** con temas, conceptos clave, y citas del profesor
5. **Extrae tareas** y deadlines a un archivo `tareas.md`

Es seguro correrlo varias veces: solo procesa lo nuevo.

## Estructura de carpetas

```
~/UADE/4to cuatrimestre/Nombre_Materia/
├── 01_Material_de_Clase/    slides, PDFs de clase
├── 02_Apuntes_Personales/   resumenes generados
├── 03_Trabajos_Practicos/   ejercicios y TPs
├── 04_Evaluaciones/         parciales y finales
├── 05_Grabaciones/          videos + transcripciones .txt
├── 06_Material_Extra/       cronogramas, bibliografia
└── tareas.md                tareas de todas las clases
```

## Como encontrar los IDs de tus equipos de Teams

1. Abrir Teams **en el browser** (teams.microsoft.com)
2. Entrar a un equipo/materia
3. Mirar la URL. Vas a ver algo asi:

```
https://teams.microsoft.com/.../Section_568898/...
                                       ^^^^^^
```

4. Ese numero (ej: `568898`) es el ID del equipo
5. Repetir para cada materia

## Personalizar los resumenes

El archivo `prompt.md` en la carpeta del proyecto contiene las instrucciones que se le dan a la IA para generar los resumenes. Podes editarlo para cambiar el formato, agregar secciones, o ajustar el estilo.

Placeholders disponibles: `{materia}`, `{clase}`, `{fecha}` — se reemplazan automaticamente.

Si borras `prompt.md`, usa un formato por defecto mas simple.

## Configuracion avanzada

Todo se configura en el archivo `.env` (se crea durante el setup). Variables disponibles:

| Variable | Para que sirve | Default |
|----------|---------------|---------|
| `UADE_BASE_DIR` | Carpeta destino | `~/UADE/4to cuatrimestre` |
| `TEAM_PREFIXES` | IDs de equipos (coma separados) | — |
| `GEMINI_API_KEY` | API key para resumenes | — |
| `WHISPER_BACKEND` | `mlx` o `openai-whisper` | Auto-detecta |
| `LLM_PROVIDER` | `claude-cli`, `gemini`, `ollama` | Auto-detecta |

## Problemas comunes

### Windows

| Problema | Solucion |
|----------|----------|
| `python` no se reconoce | Reinstalar Python marcando **"Add Python to PATH"** |
| Se abre Microsoft Store | Configuracion > Apps > Alias de ejecucion de apps > desactivar Python |
| Sesion expirada | Doble click en `uade-login.bat` para loguearte de nuevo |
| Error desconocido | Abrir el archivo de log que indica al final y enviar el contenido |

### macOS

| Problema | Solucion |
|----------|----------|
| Sesion expirada | Correr `./uade-login.sh` o el pipeline la renueva solo |
| Transcripcion lenta | Sin GPU tarda ~30-60 min por clase. Con Apple Silicon ~5 min |
| No genera resumenes | Verificar LLM: `python3 -c "from backends import llm; print(llm.detect())"` |

### General

| Problema | Solucion |
|----------|----------|
| "No hay equipos configurados" | Correr `setup.bat` (Windows) o `python3 setup.py` (macOS) |
| Resumen sin contexto de slides | Las slides deben estar en `01_Material_de_Clase/` con prefijo `CLASE_XX_` |

## Actualizar

```bash
cd uade-teams-downloader
git pull
```

---

Hecho por [Andrei Veis](https://github.com/andreiveisuade) — UADE 2026
