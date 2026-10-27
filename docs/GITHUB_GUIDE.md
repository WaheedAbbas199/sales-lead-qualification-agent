# Publishing to GitHub
1. Check no secrets: `git status` must not list `.env`; `.gitignore` already excludes it, `data/*.db`, caches.
2. ```powershell
   git init ; git add . ; git commit -m "Sales Lead Qualification Agent v1"
   git branch -M main
   git remote add origin https://github.com/<you>/sales-lead-qualification-agent.git
   git push -u origin main
   ```
3. CI (`.github/workflows/ci.yml`) runs ruff, pytest and a fresh-DB migration.
4. Add 3–4 screenshots of **synthetic** data under `docs/screenshots/` (Overview, Lead detail with score gauge, Review queue, ICP settings) and link them in the README. Capture them yourself after running the app.
5. README checklist: features ✔ install ✔ architecture diagram (docs/ARCHITECTURE.md) ✔ API docs (`/api/v1/docs`) ✔ security limitations ✔ honest classification "Production Candidate" ✔.
6. Do not claim customers, conversion lifts or compliance you have not measured.
