# Work Tracker

A personal task board (Today / Board / Week + weekly report) that Claude sessions update live.

Page: https://dulguunodgiiv123.github.io/work-tracker/

## How it stays private

- All data is one file, `tracker.enc.json`, on the `data` branch. It is encrypted with AES-256-GCM.
  The key is made from your password with PBKDF2-SHA256 (600,000 rounds), in the browser and in `wt`.
- Public: this code, the encrypted file, and when it changed. Not what it says.
- The password is the only lock. Anyone can download the file and try passwords forever, so use
  4 or more random words (`wt` refuses fewer than 12 characters).
- There is no recovery. If you forget the password, the data is gone.
- Commits use a GitHub noreply address, and every commit message is just `update`.

## Command line: `wt`

Setup on a PC (WSL or Linux, needs `gh auth login` done):

```sh
git clone https://github.com/DulguunOdgiiv123/work-tracker.git ~/work-tracker
python3 -m venv ~/work-tracker/.venv && ~/work-tracker/.venv/bin/pip install -r ~/work-tracker/tools/requirements.txt
printf '#!/bin/sh\nexec "$HOME/work-tracker/.venv/bin/python" "$HOME/work-tracker/tools/wt.py" "$@"\n' > ~/bin/wt && chmod +x ~/bin/wt
wt init          # type the password; it is saved in ~/.config/work-tracker/password (mode 600)
```

| command | what it does |
|---|---|
| `wt list` (`--all`, `-q words`) | open tasks (all with `--all`) |
| `wt add "title" --status doing --project P` | new task (`--priority`, `--detail`, `--due`, `--today`) |
| `wt set <id or title words> --status done` | change a task (`--progress 60`, `--today`, `--note "..."`) |
| `wt log "what changed" --project P` | one line in the work log |
| `wt export` | all data as JSON, decrypted |
| `wt init --from old.json` | add the tasks of an old tracker file (tasks already there are skipped) |

Every write reads the newest file, applies the change, and saves with GitHub's version check.
If someone else saved first, it retries, so the page and several Claude sessions can write at the same time.

## Page setup on a device

1. Open the page, type the password. Tick "Remember on this device" only on your own PC.
2. To edit from the page: GitHub, then Settings, Developer settings, Fine-grained tokens, Generate new token.
   Repository access: only `work-tracker`. Permissions: Contents = Read and write. Paste the token in the page's **Settings**.
   Without a token the page is read-only (Claude can still write through `wt`).

The page checks GitHub every 30 seconds (every 2 minutes without a token), so changes from Claude show up on their own.

## Files

- `index.html`: the whole page (no build step, no libraries)
- `tools/wt.py`: the command line
- `.nojekyll`: serve files as they are
