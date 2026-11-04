# secondbrain – opsætning

To repoer:
- **`secondbrain`** (privat): selve vaulten – indholdet af `vault/` her.
- **`secondbrain-mcp`**: serveren – `server/` + `docker-compose.yml`.

## 1. Vault-repo
```bash
git init secondbrain && cd secondbrain
cp -r ../secondbrain-skitse/vault/. .
git lfs install && git add -A && git commit -m "init vault"
git remote add origin git@github.com:Anders-Vestergaard/secondbrain.git && git push -u origin main
```
Git LFS på GitHub: 1 GB gratis lager/båndbredde, derefter datapakker.

## 2. Deploy key (Pi → GitHub)
```bash
ssh-keygen -t ed25519 -f secondbrain_deploy_key -N ""
```
Public key under repoets *Settings → Deploy keys* med **Allow write access**.
Private key på Pi'en i den sti, compose-filen peger på.

## 3. GitHub OAuth App (login til connectoren)
*Settings → Developer settings → OAuth Apps → New*
- Homepage: `https://brain.hestvest.dk`
- Callback: `https://brain.hestvest.dk/auth/callback`

Client ID/secret som env i Portainer-stacken, sammen med
`JWT_SIGNING_KEY` (`openssl rand -hex 32`) og `CF_TUNNEL_TOKEN`.
Kun brugere i `ALLOWED_GITHUB_USERS` slipper igennem – alle andre afvises i hvert værktøj.

## 4. Tunnel
Ny tunnel i Cloudflare Zero Trust, public hostname
`brain.hestvest.dk → http://secondbrain-mcp:8000`. Token i `CF_TUNNEL_TOKEN`.

## 5. Connector i claude.ai
*Settings → Connectors → Add custom connector*: `https://brain.hestvest.dk/mcp`.
Log ind med GitHub første gang.

## 6. Direkte upload fra chats
Så Claude kan committe store PDF'er direkte: giv sessionerne push-adgang til
`Anders-Vestergaard/secondbrain` (GitHub-forbindelsen i claude.ai). Serveren henter
ændringer inden for 60 sek., eller straks via værktøjet `sync`.

## Værktøjer
| Værktøj | Gør |
|---------|-----|
| `list_tree` | mappestruktur |
| `search` | fuldtekst i .md + filnavne |
| `read_markdown` | læs .md |
| `pdf_info` | sider, format, evt. tekst pr. side |
| `view_pdf_page` | side som billede, med zoom (`region`) |
| `write_markdown` / `append_markdown` | skriv .md + commit/push |
| `move_file` | flyt/omdøb (git mv) |
| `upload_file` | reserve: lille binær fil via base64 (max 8 MB) |
| `sync` | hent fra GitHub nu |

## Kendte grænser
- PDF-tekst indekseres ikke; søgning rammer indholdsfortegnelserne i README.md.
  Det er bevidst: tegninger har sjældent brugbar tekst.
- Én skriver ad gangen (lås i processen) – fint for én bruger.
- Testet lokalt: alle værktøjer, PDF-rendering og commit/push mod et testrepo.
  Ikke testet: GitHub-OAuth-flowet ende til ende og build på arm64.
