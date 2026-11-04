"""Second brain MCP-server.

Læser en git-vault (Markdown + PDF'er via LFS), kan vise PDF-sider som billeder,
og skriver kun .md-filer. Alle ændringer committes og pushes.
"""

from __future__ import annotations

import base64
import os
import subprocess
import threading
import time
from pathlib import Path

import pymupdf as fitz
from fastmcp import FastMCP
from fastmcp.utilities.types import Image

VAULT = Path(os.environ.get("VAULT_DIR", "/vault")).resolve()
PULL_INTERVAL = int(os.environ.get("PULL_INTERVAL_SECONDS", "60"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
GIT_AUTHOR = os.environ.get("GIT_AUTHOR", "Claude (secondbrain) <secondbrain@localhost>")
WRITABLE_TEXT = {".md"}

_git_lock = threading.Lock()
_last_pull = 0.0


# ---------------------------------------------------------------- auth
def _build_auth():
    """GitHub-OAuth, så kun Anders' GitHub-konto kan forbinde.

    Kræver en GitHub OAuth App med callback <BASE_URL>/auth/callback.
    """
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    if not client_id:
        raise RuntimeError("GITHUB_CLIENT_ID mangler – serveren starter ikke uden auth.")
    from fastmcp.server.auth.providers.github import GitHubProvider

    return GitHubProvider(
        client_id=client_id,
        client_secret=os.environ["GITHUB_CLIENT_SECRET"],
        base_url=os.environ["BASE_URL"],  # fx https://brain.hestvest.dk
        # Fast nøgle + FASTMCP_HOME på en volume => connectoren overlever genstart
        jwt_signing_key=os.environ["JWT_SIGNING_KEY"],
    )


ALLOWED_GITHUB_USERS = {
    u.strip().lower() for u in os.environ.get("ALLOWED_GITHUB_USERS", "").split(",") if u.strip()
}

mcp = FastMCP(
    "secondbrain",
    instructions=(
        "Anders' second brain: hans dokumenter (huset, el, VVS, have, kontrakter m.m.) "
        "og beslutningslogs i Markdown. Læs CLAUDE.md i roden før du placerer filer "
        "eller skriver beslutninger.\n"
        "- Søg her (search/list_tree), når chatten handler om noget, der kan ligge her, "
        "før du svarer.\n"
        "- Spørg Anders proaktivt, når chatten giver noget, der bør gemmes: en beslutning, "
        "et dokument eller et emne værd at huske – også uden for huset. Gem først efter ja.\n"
        "- Tegninger ses visuelt med view_pdf_page, ikke som tekst."
    ),
    auth=_build_auth(),
)


def _check_user() -> None:
    """Afvis alle andre end de tilladte GitHub-brugere."""
    if not ALLOWED_GITHUB_USERS:
        raise PermissionError("ALLOWED_GITHUB_USERS er ikke sat.")
    from fastmcp.server.dependencies import get_access_token

    token = get_access_token()
    login = ((token.claims or {}).get("login") or "").lower() if token else ""
    if login not in ALLOWED_GITHUB_USERS:
        raise PermissionError("Ikke autoriseret.")


# ---------------------------------------------------------------- git
def _git(*args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(VAULT), *args], capture_output=True, text=True, timeout=120
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} fejlede: {res.stderr.strip()}")
    return res.stdout


def _pull(force: bool = False) -> None:
    global _last_pull
    if not force and time.time() - _last_pull < PULL_INTERVAL:
        return
    with _git_lock:
        _git("pull", "--rebase", "--autostash")
        _git("lfs", "pull")
        _last_pull = time.time()


def _commit(paths: list[Path], message: str) -> str:
    with _git_lock:
        _git("add", *[str(p.relative_to(VAULT)) for p in paths])
        _git("-c", f"user.name={GIT_AUTHOR.split(' <')[0]}",
             "-c", f"user.email={GIT_AUTHOR.split('<')[1].rstrip('>')}",
             "commit", "-m", message)
        _git("push")
        return _git("rev-parse", "--short", "HEAD").strip()


# ---------------------------------------------------------------- stier
def _resolve(rel: str) -> Path:
    p = (VAULT / rel.lstrip("/")).resolve()
    if p != VAULT and VAULT not in p.parents:
        raise ValueError("Stien peger uden for vaulten.")
    if ".git" in p.relative_to(VAULT).parts:
        raise ValueError(".git er ikke tilgængelig.")
    return p


def _rel(p: Path) -> str:
    return str(p.relative_to(VAULT))


# ---------------------------------------------------------------- værktøjer
@mcp.tool
def list_tree(path: str = "", depth: int = 3) -> str:
    """Vis mappestrukturen (filer med størrelse). Start her for at orientere dig."""
    _check_user(); _pull()
    root = _resolve(path)
    lines: list[str] = []

    def walk(d: Path, level: int) -> None:
        for child in sorted(d.iterdir(), key=lambda c: (c.is_file(), c.name)):
            if child.name.startswith("."):
                continue
            indent = "  " * level
            if child.is_dir():
                lines.append(f"{indent}{child.name}/")
                if level + 1 < depth:
                    walk(child, level + 1)
            else:
                kb = child.stat().st_size // 1024
                lines.append(f"{indent}{child.name} ({kb} KB)")

    walk(root, 0)
    return "\n".join(lines) or "(tom)"


@mcp.tool
def search(query: str, path: str = "", max_results: int = 50) -> str:
    """Fuldtekstsøgning i Markdown (indholdsfortegnelser og beslutninger) og i filnavne."""
    _check_user(); _pull()
    root = _resolve(path)
    out: list[str] = []
    q = query.lower()
    for f in root.rglob("*"):
        if ".git" in f.parts or not f.is_file():
            continue
        if q in f.name.lower():
            out.append(f"[filnavn] {_rel(f)}")
    res = subprocess.run(
        ["rg", "--ignore-case", "--line-number", "--glob", "*.md",
         "--max-count", "5", query, str(root)],
        capture_output=True, text=True,
    )
    for line in res.stdout.splitlines():
        out.append(line.replace(str(VAULT) + "/", ""))
    return "\n".join(out[:max_results]) or "Ingen træf."


@mcp.tool
def read_markdown(path: str) -> str:
    """Læs en .md-fil, fx en mappes README.md eller CLAUDE.md."""
    _check_user(); _pull()
    p = _resolve(path)
    if p.suffix.lower() != ".md":
        raise ValueError("Kun .md – brug pdf_info/view_pdf_page til PDF'er.")
    return p.read_text(encoding="utf-8")


@mcp.tool
def pdf_info(path: str) -> str:
    """Antal sider, sidestørrelse og evt. tekst pr. side (tom tekst = tegning/scanning)."""
    _check_user(); _pull()
    doc = fitz.open(_resolve(path))
    lines = [f"{path}: {doc.page_count} sider"]
    for i, page in enumerate(doc, start=1):
        text = page.get_text().strip().replace("\n", " ")
        w, h = page.rect.width / 72 * 25.4, page.rect.height / 72 * 25.4
        lines.append(f"s.{i} ({w:.0f}x{h:.0f} mm): {text[:200] or '(ingen tekst – se visuelt)'}")
    return "\n".join(lines)


@mcp.tool
def view_pdf_page(
    path: str,
    page: int = 1,
    dpi: int = 110,
    region: list[float] | None = None,
) -> Image:
    """Vis én PDF-side som billede, så tegninger kan læses visuelt.

    region = [x0, y0, x1, y1] i brøkdele af siden (0-1) for at zoome, fx
    [0.5, 0, 1, 0.5] = øverste højre fjerdedel. Brug højere dpi ved zoom.
    """
    _check_user(); _pull()
    doc = fitz.open(_resolve(path))
    if not 1 <= page <= doc.page_count:
        raise ValueError(f"Siden findes ikke (1-{doc.page_count}).")
    pg = doc[page - 1]
    clip = None
    if region:
        r = pg.rect
        x0, y0, x1, y1 = region
        clip = fitz.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height,
                         r.x0 + x1 * r.width, r.y0 + y1 * r.height)
    dpi = max(50, min(dpi, 300))
    pix = pg.get_pixmap(dpi=dpi, clip=clip)
    # Hold billedet under ~2000 px på længste led
    while max(pix.width, pix.height) > 2000 and dpi > 50:
        dpi = int(dpi * 0.8)
        pix = pg.get_pixmap(dpi=dpi, clip=clip)
    return Image(data=pix.tobytes("png"), format="png")


@mcp.tool
def write_markdown(path: str, content: str, message: str) -> str:
    """Opret eller overskriv en .md-fil og commit. Læs filen først, hvis den findes."""
    _check_user(); _pull(force=True)
    p = _resolve(path)
    if p.suffix.lower() not in WRITABLE_TEXT:
        raise ValueError("Kun .md-filer kan skrives.")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Gemt {_rel(p)} ({_commit([p], message)})"


@mcp.tool
def append_markdown(path: str, content: str, message: str) -> str:
    """Tilføj tekst nederst i en .md-fil (fx en ny beslutning) og commit."""
    _check_user(); _pull(force=True)
    p = _resolve(path)
    if p.suffix.lower() not in WRITABLE_TEXT:
        raise ValueError("Kun .md-filer kan skrives.")
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    sep = "" if existing.endswith("\n") or not existing else "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(existing + sep + content.rstrip() + "\n", encoding="utf-8")
    return f"Tilføjet til {_rel(p)} ({_commit([p], message)})"


@mcp.tool
def move_file(src: str, dst: str, message: str) -> str:
    """Flyt/omdøb en fil (også PDF'er). Originalers indhold ændres aldrig."""
    _check_user(); _pull(force=True)
    s, d = _resolve(src), _resolve(dst)
    if d.exists():
        raise ValueError("Destinationen findes allerede.")
    d.parent.mkdir(parents=True, exist_ok=True)
    with _git_lock:
        _git("mv", _rel(s), _rel(d))
    return f"Flyttet til {_rel(d)} ({_commit([d], message)})"


@mcp.tool
def upload_file(path: str, base64_data: str, message: str) -> str:
    """Reservevej: læg en lille binær fil ind (base64). Overskriver aldrig."""
    _check_user(); _pull(force=True)
    p = _resolve(path)
    if p.exists():
        raise ValueError("Filen findes allerede – originaler overskrives ikke.")
    data = base64.b64decode(base64_data)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("For stor – commit via GitHub i stedet.")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return f"Uploadet {_rel(p)} ({_commit([p], message)})"


@mcp.tool
def sync() -> str:
    """Hent seneste ændringer fra GitHub med det samme (fx lige efter et direkte push)."""
    _check_user(); _pull(force=True)
    return _git("log", "-1", "--format=%h %s").strip()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
