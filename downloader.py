#!/usr/bin/env python3
"""UADE Teams material downloader.

Uses Playwright for auth only, then SharePoint REST API for listing/downloading.
"""

import argparse
import random
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# --- Config ---

TEAM_PREFIXES = ["568898", "561218", "558193", "562914"]
BASE_DIR = Path.home() / "UADE" / "4to cuatrimestre"
PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
SESSION_DIR = DATA_DIR / "session"
DB_PATH = DATA_DIR / "downloads.db"
SP_TENANT = "uadeeduar"
SP_BASE = f"https://{SP_TENANT}.sharepoint.com"
MAX_DOWNLOADS_PER_RUN = 50
MAX_RETRIES = 3
NAV_TIMEOUT = 30_000

FOLDER_KEYWORDS = {
    "Desarrollo_de_Aplicaciones": ["desarrollo", "aplicaciones"],
    "Ingenieria_de_Datos_II": ["ingenieria", "datos"],
    "Inteligencia_Artificial_Aplicada": ["inteligencia", "artificial"],
    "Proceso_de_Desarrollo_de_Software": ["proceso", "software"],
}

# --- Download DB ---


class DownloadDB:
    """SQLite-backed registry of downloaded files. ACID, crash-safe."""

    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                key         TEXT PRIMARY KEY,
                team_prefix TEXT NOT NULL,
                remote_path TEXT NOT NULL,
                filename    TEXT NOT NULL,
                size        INTEGER NOT NULL,
                local_path  TEXT NOT NULL,
                downloaded_at TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                files_downloaded INTEGER DEFAULT 0
            )
        """)
        self._conn.commit()
        self._migrate_manifest()

    def _migrate_manifest(self):
        """One-time migration from manifest.json if it exists."""
        manifest_path = DB_PATH.parent / "manifest.json"
        if not manifest_path.exists():
            return
        try:
            import json
            data = json.loads(manifest_path.read_text())
            count = 0
            for key, info in data.get("files", {}).items():
                if self.has(key):
                    continue
                parts = key.rsplit("|", 1)
                path_part = parts[0] if parts else key
                size = int(parts[1]) if len(parts) > 1 else 0
                segments = path_part.split("/", 1)
                prefix = segments[0]
                rest = segments[1] if len(segments) > 1 else ""
                remote_path, _, filename = rest.rpartition("/")
                self._conn.execute(
                    "INSERT OR IGNORE INTO downloads VALUES (?,?,?,?,?,?,?)",
                    (key, prefix, remote_path, filename, size,
                     info.get("local_path", ""), info.get("downloaded_at", "")),
                )
                count += 1
            self._conn.commit()
            if count:
                log(f"Migrados {count} registros de manifest.json a SQLite")
            manifest_path.rename(manifest_path.with_suffix(".json.bak"))
        except Exception as e:
            log_warn(f"Error migrando manifest.json: {e}")

    def has(self, key: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM downloads WHERE key=?", (key,)).fetchone()
        return row is not None

    def record(self, key: str, team_prefix: str, remote_path: str,
               filename: str, size: int, local_path: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO downloads VALUES (?,?,?,?,?,?,?)",
            (key, team_prefix, remote_path, filename, size,
             local_path, datetime.now().isoformat()),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]

    def start_run(self) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (started_at) VALUES (?)",
            (datetime.now().isoformat(),),
        )
        self._conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, files_downloaded: int):
        self._conn.execute(
            "UPDATE runs SET finished_at=?, files_downloaded=? WHERE id=?",
            (datetime.now().isoformat(), files_downloaded, run_id),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()


# --- Helpers ---


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(". ")


def match_team_to_folder(team_name: str) -> str:
    name_lower = team_name.lower()
    best_match = None
    best_score = 0
    for folder, keywords in FOLDER_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in name_lower)
        if score > best_score:
            best_score = score
            best_match = folder
    if best_score == 0:
        raise ValueError(f"No se pudo mapear '{team_name}' a ninguna carpeta")
    return best_match


def human_delay(lo: float = 1.0, hi: float = 3.0):
    time.sleep(random.uniform(lo, hi))


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime('%H:%M:%S')
    prefix = {"INFO": "   ", "OK": " + ", "WARN": " ! ", "ERR": "!! ", "STEP": ">>"}
    print(f"[{ts}]{prefix.get(level, '   ')} {msg}")


def log_step(msg): log(msg, "STEP")
def log_ok(msg): log(msg, "OK")
def log_warn(msg): log(msg, "WARN")
def log_err(msg): log(msg, "ERR")


# --- Browser / Auth ---


def has_session() -> bool:
    return SESSION_DIR.exists() and any(SESSION_DIR.iterdir())


def launch_browser(pw, headless: bool):
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(NAV_TIMEOUT)
    return context, page


def _is_teams_loaded(page) -> bool:
    url = page.url
    return "teams.microsoft.com" in url and "login" not in url


def ensure_logged_in(page) -> bool:
    try:
        page.wait_for_selector('nav[aria-label], [data-tid="app-bar"]', timeout=10_000)
        return True
    except PwTimeout:
        return _is_teams_loaded(page)


def wait_for_manual_login(page):
    log_step("ESPERANDO LOGIN MANUAL — logueate en el browser")
    deadline = time.time() + 300
    while time.time() < deadline:
        if _is_teams_loaded(page):
            log_ok("Login detectado")
            human_delay(3, 5)
            return
        time.sleep(3)
    raise RuntimeError("Timeout esperando login (5 min)")


def get_sp_session(context) -> requests.Session:
    """Create a requests session with SharePoint auth cookies."""
    session = requests.Session()
    cookies = context.cookies(f"{SP_BASE}")
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c["domain"])
    session.headers.update({
        "Accept": "application/json;odata=verbose",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    })
    return session


# --- SharePoint API ---


def sp_discover_all_libraries(session: requests.Session, site_url: str) -> list[dict]:
    """Find ALL document libraries worth crawling."""
    url = f"{site_url}/_api/web/lists?$filter=BaseTemplate eq 101&$select=Title,RootFolder/ServerRelativeUrl,ItemCount&$expand=RootFolder"
    log(f"  Discovering document libraries...")
    resp = session.get(url)
    resp.raise_for_status()
    libs = resp.json()["d"]["results"]

    SKIP = {"activos del sitio", "site assets", "biblioteca de estilos", "style library",
            "plantillas de formulario", "form templates", "formservertemplates"}

    results = []
    for lib in libs:
        title = lib["Title"]
        root = lib["RootFolder"]["ServerRelativeUrl"]
        count = lib.get("ItemCount", 0)
        skip = title.lower() in SKIP

        status = "SKIP" if skip else f"{count} items"
        log(f"    {'  ' if skip else '+'} Library: '{title}' → {root} ({status})")

        if not skip:
            results.append({"title": title, "root": root, "count": count})

    log_ok(f"  {len(results)} libraries a crawlear")
    return results


def sp_list_folder(session: requests.Session, site_url: str, folder_path: str) -> list[dict]:
    """List files and folders in a SharePoint folder."""
    encoded_path = urllib.parse.quote(folder_path)

    # Get subfolders
    folders_url = f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{encoded_path}')/Folders"
    resp = session.get(folders_url)
    resp.raise_for_status()
    folders = []
    for f in resp.json()["d"]["results"]:
        name = f["Name"]
        if name in ("Forms",):
            continue
        folders.append({
            "name": name,
            "is_folder": True,
            "size": 0,
            "server_relative_url": f["ServerRelativeUrl"],
        })

    # Get files
    files_url = f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{encoded_path}')/Files"
    resp = session.get(files_url)
    resp.raise_for_status()
    files = []
    for f in resp.json()["d"]["results"]:
        files.append({
            "name": f["Name"],
            "is_folder": False,
            "size": int(f["Length"]),
            "server_relative_url": f["ServerRelativeUrl"],
        })

    return folders + files


def sp_download_file(session: requests.Session, site_url: str, file_url: str, dest_path: Path) -> bool:
    """Download a file from SharePoint using the REST API."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".downloading")

    if tmp_path.exists():
        tmp_path.unlink()

    encoded = urllib.parse.quote(file_url, safe="/")
    download_url = f"{site_url}/_api/web/GetFileByServerRelativeUrl('{encoded}')/$value"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(download_url, stream=True, timeout=300)
            resp.raise_for_status()

            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0

            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)

            if not tmp_path.exists() or tmp_path.stat().st_size == 0:
                raise RuntimeError("Archivo vacío")

            size_mb = tmp_path.stat().st_size / (1024 * 1024)
            tmp_path.rename(dest_path)
            log_ok(f"    OK: {dest_path.name} ({size_mb:.1f} MB)")
            return True

        except Exception as e:
            err = str(e).split("\n")[0][:120]
            log_err(f"    Intento {attempt}/{MAX_RETRIES}: {err}")
            if tmp_path.exists():
                tmp_path.unlink()
            if attempt < MAX_RETRIES:
                backoff = [5, 15, 45][attempt - 1]
                log(f"    Reintentando en {backoff}s...")
                time.sleep(backoff)
            else:
                log_err(f"    Falló después de {MAX_RETRIES} intentos")
                return False

    return False


# --- Crawl ---


def crawl_folder(
    session: requests.Session,
    site_url: str,
    folder_path: str,
    remote_label: str,
    local_base: Path,
    db: DownloadDB,
    team_prefix: str,
    download_count: list,
):
    if download_count[0] >= MAX_DOWNLOADS_PER_RUN:
        log_warn(f"Límite de {MAX_DOWNLOADS_PER_RUN} descargas alcanzado")
        return

    log_step(f"Listando: {remote_label}")
    try:
        items = sp_list_folder(session, site_url, folder_path)
    except Exception as e:
        log_err(f"Error listando {folder_path}: {str(e)[:100]}")
        return

    folders = [i for i in items if i["is_folder"]]
    files = [i for i in items if not i["is_folder"]]
    log(f"Encontrados: {len(files)} archivos, {len(folders)} carpetas")

    for f in files:
        log(f"    archivo: {f['name']} ({f['size'] / 1024:.0f} KB)")
    for f in folders:
        log(f"    carpeta: {f['name']}")

    # Download files
    skipped = 0
    for item in files:
        if download_count[0] >= MAX_DOWNLOADS_PER_RUN:
            break

        name = sanitize_filename(item["name"])
        db_key = f"{team_prefix}/{remote_label}/{name}|{item['size']}"

        if db.has(db_key):
            skipped += 1
            continue

        dest = local_base / remote_label / name
        log_step(f"Descargando: {remote_label}/{name}")

        if sp_download_file(session, site_url, item["server_relative_url"], dest):
            db.record(db_key, team_prefix, remote_label, name,
                      item["size"], str(dest))
            download_count[0] += 1
            human_delay(3, 5)
        else:
            log_err(f"SKIP (falló): {name}")

    if skipped > 0:
        log(f"{skipped} archivos ya descargados (skip)")

    # Recurse into subfolders
    for item in folders:
        if download_count[0] >= MAX_DOWNLOADS_PER_RUN:
            break
        sub_label = f"{remote_label}/{item['name']}"
        crawl_folder(
            session, site_url, item["server_relative_url"],
            sub_label, local_base, db, team_prefix, download_count,
        )
        human_delay(1, 2)


# --- Teams navigation (only for finding team names) ---


def find_team_name(page, prefix: str) -> str:
    """Navigate Teams UI to find the full team name for a prefix."""
    # Click Teams/Equipos in sidebar
    selectors = [
        'button[aria-label*="Equipos"]',
        'button[aria-label*="Teams"]',
        'button[data-tid="teams-button"]',
    ]
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            loc.first.click()
            human_delay(2, 3)
            page.wait_for_load_state("networkidle")
            break

    # Find team by prefix
    try:
        team_el = page.locator(f'text=/{prefix}/').first
        team_el.wait_for(timeout=10_000)
        return team_el.text_content().strip()
    except PwTimeout:
        raise RuntimeError(f"Team {prefix} no encontrado en Teams")


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Descarga material de Teams UADE")
    parser.add_argument("--visible", action="store_true", help="Forzar browser visible")
    parser.add_argument("--team", type=str, help="Descargar solo un team (prefijo)")
    args = parser.parse_args()

    prefixes = [args.team] if args.team else TEAM_PREFIXES
    db = DownloadDB()
    headless = not args.visible and has_session()

    print()
    print("=" * 60)
    print("  UADE Teams Downloader")
    print("=" * 60)
    log(f"Modo: {'HEADLESS' if headless else 'VISIBLE'}")
    log(f"Teams: {', '.join(prefixes)}")
    log(f"Destino: {BASE_DIR}")
    log(f"DB: {DB_PATH}")
    already = db.count()
    if already:
        log(f"Archivos registrados: {already}")
    print("-" * 60)

    with sync_playwright() as pw:
        log_step("Abriendo browser...")
        context, page = launch_browser(pw, headless=headless)

        try:
            log_step("Navegando a Teams...")
            page.goto("https://teams.microsoft.com", wait_until="domcontentloaded")
            human_delay(3, 5)

            if not ensure_logged_in(page):
                if headless:
                    log_warn("Sin sesión. Relanzando visible...")
                    context.close()
                    context, page = launch_browser(pw, headless=False)
                    page.goto("https://teams.microsoft.com", wait_until="domcontentloaded")
                    human_delay(3, 5)
                wait_for_manual_login(page)
            else:
                log_ok("Sesión activa")

            # Need to visit SharePoint to get cookies
            log_step("Obteniendo cookies de SharePoint...")
            # Navigate to a SharePoint page to ensure cookies are set
            sp_test_url = f"{SP_BASE}/sites/Section_{prefixes[0]}/_api/web/title"
            page.goto(sp_test_url, wait_until="networkidle")
            human_delay(2, 3)

            # Check if we got redirected to login
            if "login" in page.url.lower():
                log("Redirigido a login de SharePoint, esperando auth...")
                page.wait_for_url(f"**{SP_TENANT}.sharepoint.com**", timeout=60_000)
                human_delay(2, 3)

            # Create requests session with cookies
            sp_session = get_sp_session(context)

            # Verify API access
            test_resp = sp_session.get(f"{SP_BASE}/sites/Section_{prefixes[0]}/_api/web/title")
            if test_resp.status_code != 200:
                log_err(f"API de SharePoint no accesible (HTTP {test_resp.status_code})")
                log("Probando re-auth...")
                page.goto(f"{SP_BASE}/sites/Section_{prefixes[0]}", wait_until="networkidle")
                human_delay(5, 8)
                sp_session = get_sp_session(context)
                test_resp = sp_session.get(f"{SP_BASE}/sites/Section_{prefixes[0]}/_api/web/title")
                test_resp.raise_for_status()

            log_ok("API de SharePoint accesible")

            # Now go back to Teams to find team names
            page.goto("https://teams.microsoft.com", wait_until="domcontentloaded")
            human_delay(5, 8)

            print("-" * 60)
            download_count = [0]
            run_id = db.start_run()

            for i, prefix in enumerate(prefixes):
                print()
                print(f"{'=' * 60}")
                log_step(f"TEAM {i+1}/{len(prefixes)}: {prefix}")
                print(f"{'=' * 60}")

                try:
                    team_name = find_team_name(page, prefix)
                    log_ok(f"Team: {team_name}")

                    folder = match_team_to_folder(team_name)
                    local_dest = BASE_DIR / folder / "teams_material"
                    site_url = f"{SP_BASE}/sites/Section_{prefix}"

                    log(f"Materia: {folder}")
                    log(f"Destino: {local_dest}")
                    log(f"SharePoint: {site_url}")
                    print("-" * 40)

                    # Discover ALL document libraries and crawl each one
                    libraries = sp_discover_all_libraries(sp_session, site_url)

                    for lib in libraries:
                        if download_count[0] >= MAX_DOWNLOADS_PER_RUN:
                            break
                        lib_label = lib["title"]
                        log_step(f"Crawleando library: {lib_label}")
                        crawl_folder(
                            sp_session, site_url, lib["root"],
                            lib_label, local_dest, db, prefix, download_count,
                        )

                    log_ok(f"Team {prefix} completado")

                except Exception as e:
                    log_err(f"Error en team {prefix}: {str(e)[:150]}")

                if download_count[0] >= MAX_DOWNLOADS_PER_RUN:
                    log_warn(f"Límite de descargas ({MAX_DOWNLOADS_PER_RUN})")
                    break

                if prefix != prefixes[-1]:
                    delay = random.uniform(10, 15)
                    log(f"Pausa de {delay:.0f}s...")
                    time.sleep(delay)

            db.finish_run(run_id, download_count[0])
            print()
            print("=" * 60)
            log_ok(f"RESUMEN: {download_count[0]} archivos descargados")
            log(f"Total registrados: {db.count()}")
            print("=" * 60)

        finally:
            db.close()
            context.close()
            log("Browser cerrado")


if __name__ == "__main__":
    main()
