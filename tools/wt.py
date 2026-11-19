#!/usr/bin/env python3
"""wt - read and update the encrypted Work Tracker from the command line.

The tracker is one file, tracker.enc.json, on the `data` branch of the GitHub repo.
It is encrypted with AES-256-GCM; the key comes from your password via PBKDF2-SHA256.
The password is stored only on this PC, in ~/.config/work-tracker/password (mode 600).

    wt init [--from tracker.json]      set the password (and upload the first data)
    wt list [--all] [-q TEXT]          show tasks (open ones by default)
    wt add "title" [--status doing] [--project P] [--priority high] [--today]
    wt set <id|words> [--status S] [--progress N] [--today] [--note TEXT] ...
    wt log "what changed" [--project P] [--task <id|words>]
    wt export                          print the decrypted JSON
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO = os.environ.get('WT_REPO', 'DulguunOdgiiv123/work-tracker')
BRANCH = os.environ.get('WT_BRANCH', 'data')
FILE = 'tracker.enc.json'
CONF = Path(os.environ.get('WT_CONF', str(Path.home() / '.config' / 'work-tracker')))
PWFILE = CONF / 'password'
ITER = 600_000
NOREPLY = {'name': 'work-tracker', 'email': 'DulguunOdgiiv123@users.noreply.github.com'}
STATUSES = ('todo', 'doing', 'done', 'postponed')
PRIOS = ('high', 'medium', 'low')
MIN_PASSWORD = 12


class WtError(Exception):
    pass


class Conflict(Exception):
    pass


# ---------- crypto (same format as index.html) ----------
def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode('ascii')


def b64d(s: str) -> bytes:
    return base64.b64decode(s)


def derive(password: str, salt: bytes, iters: int) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iters, 32)


def encrypt(state: dict, key: bytes, salt: bytes, iters: int) -> dict:
    iv = secrets.token_bytes(12)
    plain = json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return {'v': 1, 'kdf': 'PBKDF2-SHA256', 'iter': iters, 'salt': b64e(salt), 'iv': b64e(iv),
            'ct': b64e(AESGCM(key).encrypt(iv, plain, None))}


def decrypt(blob: dict, password: str):
    if blob.get('v') != 1:
        raise WtError(f"unknown file version {blob.get('v')!r}")
    salt, iters = b64d(blob['salt']), int(blob['iter'])
    key = derive(password, salt, iters)
    try:
        plain = AESGCM(key).decrypt(b64d(blob['iv']), b64d(blob['ct']), None)
    except Exception:
        raise WtError('wrong password, or the file was damaged') from None
    return json.loads(plain), key, salt, iters


# ---------- GitHub (through the gh CLI, which already holds your login) ----------
def gh(args: list[str], body: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(['gh', 'api', *args], input=json.dumps(body) if body else None,
                              capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise WtError('the gh CLI is not installed') from None
    except subprocess.TimeoutExpired:
        raise WtError('GitHub did not answer within 60 s') from None


def fetch() -> tuple[dict | None, str | None]:
    r = gh([f'repos/{REPO}/contents/{FILE}?ref={BRANCH}'])
    if r.returncode != 0:
        msg = (r.stdout + r.stderr).strip()
        if 'HTTP 404' in msg or 'Not Found' in msg:
            return None, None
        raise WtError('GitHub read failed: ' + msg[:300])
    j = json.loads(r.stdout)
    return json.loads(base64.b64decode(j['content'])), j['sha']


def put(blob: dict, sha: str | None) -> None:
    body = {'message': 'update', 'branch': BRANCH, 'committer': NOREPLY, 'author': NOREPLY,
            'content': b64e(json.dumps(blob, separators=(',', ':')).encode('ascii'))}
    if sha:
        body['sha'] = sha
    r = gh(['-X', 'PUT', f'repos/{REPO}/contents/{FILE}', '--input', '-'], body)
    if r.returncode != 0:
        msg = (r.stdout + r.stderr).strip()
        if 'HTTP 409' in msg or ('HTTP 422' in msg and 'sha' in msg):
            raise Conflict()
        raise WtError('GitHub write failed: ' + msg[:300])


# ---------- data model (mirrors index.html) ----------
def today() -> str:
    return date.today().isoformat()


def monday(d: str) -> str:
    x = date.fromisoformat(d)
    return (x - timedelta(days=x.weekday())).isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def new_id() -> str:
    return 't' + format(int(time.time() * 1000), 'x') + secrets.token_hex(3)


def norm(s) -> str:
    return ' '.join(str(s or '').lower().split())


def normalize(s: dict | None) -> dict:
    s = s if isinstance(s, dict) else {}
    return {'version': 1, 'items': list(s.get('items') or []), 'weekNotes': dict(s.get('weekNotes') or {}),
            'log': list(s.get('log') or []), 'meta': dict(s.get('meta') or {})}


def make_item(**kw) -> dict:
    now = now_iso()
    it = {'id': new_id(), 'title': '', 'detail': '', 'status': 'todo', 'progress': 0, 'priority': 'medium',
          'start': None, 'due': None, 'done_on': None, 'week': monday(today()), 'project': '', 'today': None,
          'notes': '', 'source': 'claude', 'source_keys': [], 'reviewed': True, 'log': [],
          'created': now, 'updated': now}
    it.update(kw)
    return it


def touch(it: dict, d: str | None = None) -> None:
    """Record the status/progress of day d in the item's history (one entry per day)."""
    d = d or today()
    if it['status'] == 'done':
        it['progress'] = 100
        it['done_on'] = it.get('done_on') or d
    else:
        it['done_on'] = None
    if it['status'] == 'doing' and not it.get('start'):
        it['start'] = d
    log = it.setdefault('log', [])
    hit = next((e for e in log if e['d'] == d), None)
    if hit:
        hit['s'], hit['p'] = it['status'], it['progress']
    else:
        log.append({'d': d, 's': it['status'], 'p': it['progress']})
        log.sort(key=lambda e: e['d'])
    it['updated'] = now_iso()


def short(it: dict) -> str:
    return it['id'][-6:]


def find(state: dict, ref: str) -> dict:
    items = state['items']
    for it in items:
        if it['id'] == ref:
            return it
    if len(ref) >= 4:
        by_id = [i for i in items if i['id'].endswith(ref)]
        if len(by_id) == 1:
            return by_id[0]
    q = norm(ref)
    hits = [i for i in items if q and q in norm(i['title'])]
    if len(hits) == 1:
        return hits[0]
    open_hits = [i for i in hits if i['status'] in ('todo', 'doing')]
    if len(open_hits) == 1:
        return open_hits[0]
    if not hits:
        raise WtError(f'no task matches {ref!r}. Try: wt list --all -q "<words>"')
    raise WtError('several tasks match, use the id:\n' + '\n'.join(line(i) for i in hits[:10]))


def line(it: dict) -> str:
    proj = f"[{it['project']}] " if it.get('project') else ''
    tday = '  (today)' if it.get('today') == today() else ''
    return f"{short(it)}  {it['status']:<9} {it['progress']:>3}%  {it['priority']:<6} {proj}{it['title']}{tday}"


# ---------- password ----------
def read_password() -> str:
    if os.environ.get('WT_PASSWORD'):
        return os.environ['WT_PASSWORD']
    try:
        return PWFILE.read_text(encoding='utf-8').rstrip('\n')
    except FileNotFoundError:
        raise WtError(f'not set up on this PC: run `wt init` in your own terminal ({PWFILE} is missing)') from None


def save_password(pw: str) -> None:
    CONF.mkdir(parents=True, exist_ok=True)
    os.chmod(CONF, stat.S_IRWXU)
    fd = os.open(PWFILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(pw + '\n')
    os.chmod(PWFILE, 0o600)


# ---------- read-modify-write with retry ----------
def load() -> dict:
    blob, _ = fetch()
    if blob is None:
        raise WtError('no tracker data on GitHub yet: run `wt init` first')
    return normalize(decrypt(blob, read_password())[0])


def update(op):
    pw = read_password()
    for attempt in range(6):
        blob, sha = fetch()
        if blob is None:
            raise WtError('no tracker data on GitHub yet: run `wt init` first')
        raw, key, salt, iters = decrypt(blob, pw)
        state = normalize(raw)
        result = op(state)
        try:
            put(encrypt(state, key, salt, iters), sha)
            return result
        except Conflict:
            time.sleep(0.4 * (attempt + 1))  # someone else saved first: re-read and apply again
    raise WtError('gave up: the file kept changing during 6 tries')


def merge_into(state: dict, incoming: dict) -> tuple[int, int]:
    """Add what `incoming` has and `state` lacks. A task counts as present when its id or its title is
    already there, so running the same merge twice adds nothing. Returns (tasks added, tasks skipped)."""
    ids = {i['id'] for i in state['items']}
    titles = {norm(i['title']) for i in state['items']}
    added = 0
    for it in incoming['items']:
        if it.get('id') in ids or norm(it.get('title')) in titles:
            continue
        state['items'].append(it)
        added += 1
    log_ids = {e.get('id') for e in state['log']}
    state['log'] += [e for e in incoming['log'] if e.get('id') not in log_ids]
    for week, text in incoming['weekNotes'].items():
        if text and not state['weekNotes'].get(week):
            state['weekNotes'][week] = text
    return added, len(incoming['items']) - added


# ---------- commands ----------
def cmd_init(a) -> str:
    # read the file first, so a wrong path fails before any password prompt
    try:
        incoming = normalize(json.loads(Path(a.from_file).read_text(encoding='utf-8'))) if a.from_file else None
    except (OSError, ValueError) as e:
        raise WtError(f'cannot read {a.from_file}: {e}') from None
    blob, sha = fetch()
    if blob is not None:
        try:
            decrypt(blob, read_password())  # this PC already has a working password: don't ask again
            msg = 'this PC is already set up'
        except WtError:
            pw = getpass.getpass('Tracker password: ')
            decrypt(blob, pw)  # raises on a wrong password
            save_password(pw)
            msg = f'password saved in {PWFILE}; this PC can now update the tracker'
        if incoming is not None:
            added, skipped = update(lambda s: merge_into(s, incoming))
            msg += f'\nadded {added} tasks from {a.from_file} ({skipped} were already there)'
        return msg
    pw = getpass.getpass(f'New tracker password (at least {MIN_PASSWORD} characters, e.g. 4 random words): ')
    if len(pw) < MIN_PASSWORD:
        raise WtError(f'too short: use at least {MIN_PASSWORD} characters')
    if getpass.getpass('Repeat it: ') != pw:
        raise WtError('the two passwords differ')
    state = incoming or normalize(None)
    salt = secrets.token_bytes(16)
    put(encrypt(state, derive(pw, salt, ITER), salt, ITER), None)
    save_password(pw)
    return f'created the tracker with {len(state["items"])} tasks; password saved in {PWFILE}'


def cmd_list(a) -> str:
    s = load()
    items = s['items']
    if not a.all:
        items = [i for i in items if i['status'] in ('todo', 'doing')]
    if a.q:
        items = [i for i in items if norm(a.q) in norm(f"{i['title']} {i.get('detail', '')} {i.get('project', '')}")]
    if a.project:
        items = [i for i in items if norm(i.get('project')) == norm(a.project)]
    order = {'doing': 0, 'todo': 1, 'postponed': 2, 'done': 3}
    items.sort(key=lambda i: (order[i['status']], PRIOS.index(i['priority']) if i['priority'] in PRIOS else 1,
                              i.get('due') or '9999'))
    if a.json:
        return json.dumps(items, ensure_ascii=False, indent=1)
    return '\n'.join(line(i) for i in items) or '(no tasks)'


def cmd_add(a) -> str:
    def op(s):
        dup = [i for i in s['items'] if norm(i['title']) == norm(a.title) and i['status'] in ('todo', 'doing')]
        if dup and not a.force:
            raise WtError(f'already open: {line(dup[0])}  (use wt set, or --force)')
        it = make_item(title=a.title.strip(), status=a.status, priority=a.priority, project=a.project or '',
                       detail=a.detail or '', due=a.due, today=today() if a.today else None)
        touch(it)
        s['items'].append(it)
        return 'added ' + line(it)
    return update(op)


def cmd_set(a) -> str:
    def op(s):
        it = find(s, a.ref)
        before = (it['status'], it['progress'])
        if a.status:
            it['status'] = a.status
        if a.progress is not None:
            it['progress'] = max(0, min(100, a.progress))
            if it['status'] == 'todo' and it['progress'] > 0 and not a.status:
                it['status'] = 'doing'
        for k in ('title', 'project', 'priority', 'detail', 'due'):
            v = getattr(a, k)
            if v is not None:
                it[k] = v.strip() if isinstance(v, str) else v
        if a.today:
            it['today'] = today()
        if a.no_today:
            it['today'] = None
        if a.note:
            it['notes'] = (it.get('notes', '') + f"\n{today()}: {a.note.strip()}").strip()
        it['reviewed'] = True
        if (it['status'], it['progress']) != before or a.today:
            touch(it)
        else:
            it['updated'] = now_iso()
        return 'updated ' + line(it)
    return update(op)


def cmd_log(a) -> str:
    def op(s):
        task = find(s, a.task)['id'] if a.task else None
        s['log'].append({'id': new_id(), 'd': today(), 't': datetime.now().strftime('%H:%M'),
                         'text': a.text.strip(), 'project': a.project or '', 'task': task,
                         'src': socket.gethostname()})
        return f'logged: {a.text.strip()}'
    return update(op)


def cmd_export(a) -> str:
    return json.dumps(load(), ensure_ascii=False, indent=1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='wt', description='Update the encrypted Work Tracker.')
    sub = p.add_subparsers(dest='cmd', required=True)
    x = sub.add_parser('init', help='set the password on this PC (and create the data the first time)')
    x.add_argument('--from', dest='from_file',
                   help='old tracker.json: its tasks are added (tasks already there are skipped)')
    x = sub.add_parser('list', help='show tasks')
    x.add_argument('--all', action='store_true', help='include done and postponed')
    x.add_argument('-q', help='search text')
    x.add_argument('--project')
    x.add_argument('--json', action='store_true')
    x = sub.add_parser('add', help='add a task')
    x.add_argument('title')
    x.add_argument('--status', choices=STATUSES, default='todo')
    x.add_argument('--priority', choices=PRIOS, default='medium')
    x.add_argument('--project')
    x.add_argument('--detail')
    x.add_argument('--due', type=lambda v: date.fromisoformat(v).isoformat())
    x.add_argument('--today', action='store_true', help="put it on today's list")
    x.add_argument('--force', action='store_true', help='add even if an open task has the same title')
    x = sub.add_parser('set', help='change a task (id from `wt list`, or words from its title)')
    x.add_argument('ref')
    x.add_argument('--status', choices=STATUSES)
    x.add_argument('--progress', type=int)
    x.add_argument('--title')
    x.add_argument('--project')
    x.add_argument('--priority', choices=PRIOS)
    x.add_argument('--detail')
    x.add_argument('--due', type=lambda v: date.fromisoformat(v).isoformat())
    x.add_argument('--note', help='append a dated note')
    g = x.add_mutually_exclusive_group()
    g.add_argument('--today', action='store_true')
    g.add_argument('--no-today', action='store_true')
    x = sub.add_parser('log', help='add one line to the work log')
    x.add_argument('text')
    x.add_argument('--project')
    x.add_argument('--task', help='link the line to a task (id or title words)')
    sub.add_parser('export', help='print all data as JSON (decrypted)')
    a = p.parse_args(argv)
    try:
        print({'init': cmd_init, 'list': cmd_list, 'add': cmd_add, 'set': cmd_set,
               'log': cmd_log, 'export': cmd_export}[a.cmd](a))
        return 0
    except WtError as e:
        print(f'wt: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
