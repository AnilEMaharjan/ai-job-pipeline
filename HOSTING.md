# Hosting for a few friends (2–5), free, on your always-on Mac

Goal: let a handful of friends each run their own job search through a browser,
with **no per-user code**, **no paid hosting**, and **no public exposure**. Each
person gets an independent instance; you (the host) cover the Anthropic API cost.

## How it works
- Each user = an independent **git clone** with its own `config/` (their resume),
  its own `data/jobs.db`, and its own **port**. Isolation is automatic because the
  data lives in separate folders — no multi-tenant code needed.
- All instances share **one Anthropic key** (yours) via a per-clone `.env`.
- **Tailscale** provides access + auth for free: each dashboard binds to the Mac's
  Tailscale IP, so only devices on *your* private tailnet can reach it. Not the LAN,
  not the internet.
- **launchd** keeps each dashboard running and runs a daily `fetch`+`score`.

```
~/jobpipe/
  shared.env            # ANTHROPIC_API_KEY=sk-ant-...   (chmod 600, host pays)
  users/
    alice/  (clone, port 8767)
    bob/    (clone, port 8768)
```

## One-time host setup
1. **Install Tailscale** on the Mac and log in: https://tailscale.com/download
   Get the Mac's tailnet IP: `tailscale ip -4`  (looks like `100.x.y.z`).
2. **Install prereqs**: `git`, Python 3.11+. (TinyTeX only if friends will export PDFs.)
3. **Create the shared key file**:
   ```bash
   mkdir -p ~/jobpipe && echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/jobpipe/shared.env
   chmod 600 ~/jobpipe/shared.env
   ```

## Add a friend (one command, then it's self-service)
From a checkout of this repo:
```bash
scripts/new-user.sh alice 8767 100.x.y.z     # <name> <port> <mac-tailscale-ip>
```
That clones, builds the venv, seeds config templates, wires your key, and installs
two launchd services (dashboard + daily fetch/score). Then:
1. **Invite the friend to your Tailscale network** (Tailscale admin console → invite
   by email), then send them `http://100.x.y.z:8767`.
2. That's it on your end. **They do the rest themselves in the browser** — no one
   touches the Mac's filesystem for them:
   - Open the URL → click **⚙ Profile** → **Resume** tab → upload their resume
     (PDF or .txt) → **✨ Parse with AI** converts it to the app's schema →
     they review/edit the JSON → **💾 Save Profile**.
   - They also fill in the **Personal** and **Notes** tabs (same page).
   - **Title Filters** and **Scoring Rules** tabs are the important ones for a
     new domain (e.g. a friend in marketing, not data/analytics): these decide
     which job titles even reach AI scoring, and what "good fit" means for
     their career. The page shows the generic `.example` template as a
     starting point (with a ⚠ note that it isn't saved yet) — they should edit
     it to their own titles/persona/dealbreakers, then Save. **Without this,
     every job title is filtered out** (a loud warning prints on fetch) — this
     is deliberate (never silently score jobs against unconfigured filters),
     but it means a friend who skips this step will see zero results.
   - Click **⟳ Fetch & Score** in the header to run their first fetch + scoring pass.

Give each friend a **different port** (8767, 8768, 8769, …).

(If you'd rather do a friend's profile setup yourself from the host side instead —
e.g. they're not comfortable poking at JSON — `scripts/import_resume.py` does the
same PDF/text → resume.json conversion as the Profile page's upload button, just
from the command line: `cd ~/jobpipe/users/alice && ./.venv/bin/python scripts/import_resume.py ~/Downloads/alice_resume.pdf`.)

## Updating everyone after a code change
```bash
scripts/update-all.sh
```
Pulls latest code + deps into every instance and restarts the dashboards. Their
data and config are gitignored, so nothing personal is touched.

## The cost to watch (you're paying)
Hosting is free, but **scoring/generation call the Anthropic API per user**. Cost
scales ~linearly with friends (each scores against their own resume, so it can't be
shared). Prompt caching + in-lane-only scoring keep it modest, but watch the first
week's spend and cap the number of friends if it stings. If one friend gets
expensive, move just them to their own key (next section) — no reprovisioning.

## Switching a friend to their own key (BYO-key, any time)
Each instance reads its key from its own `.env`, so you can flip a single user
between the shared host key and their own key whenever you want:
```bash
scripts/set-user-key.sh alice sk-ant-...   # Alice pays for her own scoring
scripts/set-user-key.sh alice --shared      # revert Alice to the shared host key
```
It rewrites only that user's `.env` (chmod 600) and restarts their dashboard. The
daily fetch/score is a fresh process, so it picks up the new key on its next run.
Nobody else is affected — the cheap way to keep hosting free for casual friends
while making heavy users cover their own API cost.

## Security notes
- Dashboards bind to the **Tailscale IP only** — never `0.0.0.0` on an untrusted
  network. Access requires being on your tailnet.
- The app itself has **no login**; Tailscale *is* the access control. Only invite
  people you trust — anyone on the tailnet who knows the port can view **and edit**
  that instance, including its Profile page (resume/personal/notes).
- `shared.env` and each `.env` hold your API key: keep them `chmod 600`, never commit
  (they're gitignored).

## Removing a friend
```bash
launchctl unload ~/Library/LaunchAgents/com.jobpipe.alice.dashboard.plist
launchctl unload ~/Library/LaunchAgents/com.jobpipe.alice.daily.plist
rm ~/Library/LaunchAgents/com.jobpipe.alice.*.plist
rm -rf ~/jobpipe/users/alice
```
And remove them from your Tailscale network in the admin console.

## When to graduate to a real multi-user app
This setup is right for ~2–5 trusted friends. If you want 10s of users, public
signup, or to charge, that's a genuine build: accounts, Postgres, per-user
bring-your-own-key, and a job queue. Don't force this approach past its scale.
