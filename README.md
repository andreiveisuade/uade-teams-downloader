# UADE Teams Downloader

Descarga automática de material de clases desde Microsoft Teams / SharePoint de UADE.

## Estructura

```
downloader.py                          # Script principal de descarga
run-downloader.sh                      # Wrapper para launchd (activa venv, loguea)
com.andreiveis.uade-downloader.plist   # launchd agent (copia versionada)
requirements.txt                       # Dependencias Python
data/                                  # (gitignored)
├── downloads.db                       # SQLite: archivos descargados + runs
├── session/                           # Browser context persistente (Playwright)
└── logs/                              # Logs de ejecuciones automáticas
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Primera ejecución (login manual)

```bash
python3 downloader.py --visible
```

Se abre Chromium. Loguearse en Teams con cuenta UADE. La sesión queda guardada en `data/session/` y las siguientes ejecuciones corren headless.

## Uso manual

```bash
source .venv/bin/activate
python3 downloader.py              # Todas las materias
python3 downloader.py --team 568898  # Solo IA Aplicada
```

## Automatización (launchd)

### Horarios programados

| Materia                        | Prefijo | Clase termina | Descarga corre |
|-------------------------------|---------|---------------|----------------|
| IA Aplicada                    | 568898  | Lun 22:45     | Lun 23:45      |
| PDS                            | 558193  | Mar 11:45     | Mar 12:45      |
| Desarrollo de Aplicaciones I   | 562914  | Jue 11:45     | Jue 18:30      |
| Ingeniería de Datos II         | 561218  | Jue 17:30     | Jue 18:30      |

El jueves corre una sola vez a las 18:30 y baja material de ambas materias.

### Instalar el agent

```bash
cp com.andreiveis.uade-downloader.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
```

### Verificar

```bash
launchctl list | grep uade                          # Ver si está cargado
launchctl start com.andreiveis.uade-downloader      # Forzar ejecución
ls -lt data/logs/                                    # Ver logs
sqlite3 data/downloads.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5;"
```

### Desinstalar

```bash
launchctl unload ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
rm ~/Library/LaunchAgents/com.andreiveis.uade-downloader.plist
```

## Troubleshooting

- **No descarga nada**: La sesión de Teams expiró. Correr `python3 downloader.py --visible` para re-loguearse.
- **Logs vacíos**: Verificar que el venv tiene las dependencias (`pip install -r requirements.txt`).
- **launchd no corre**: Si la Mac estaba dormida, `StartCalendarInterval` ejecuta al despertar. Si no aparece con `launchctl list`, re-cargar el plist.
- **PID en launchctl list**: Significa que hay una ejecución en curso. No lanzar otra hasta que termine.

## Materias (4to cuatrimestre)

| Materia                        | Prefijo | Carpeta destino                          |
|-------------------------------|---------|------------------------------------------|
| IA Aplicada                    | 568898  | ~/UADE/4to cuatrimestre/Inteligencia_Artificial_Aplicada/ |
| PDS                            | 558193  | ~/UADE/4to cuatrimestre/Proceso_de_Desarrollo_de_Software/ |
| Desarrollo de Aplicaciones I   | 562914  | ~/UADE/4to cuatrimestre/Desarrollo_de_Aplicaciones/ |
| Ingeniería de Datos II         | 561218  | ~/UADE/4to cuatrimestre/Ingenieria_de_Datos_II/ |
