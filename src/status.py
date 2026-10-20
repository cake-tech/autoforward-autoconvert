"""Machine-readable heartbeat for monitoring.

Each program keeps one dict per section (a coin, an asset) and rewrites
STATUS_DIR/<program>.json after every pass, atomically. A monitor reads
`updated` for liveness and each section's `last_ok` / `last_error_at` /
`errors_total` for health. Nothing is written when STATUS_DIR is unset.

Error text is truncated and stored as-is: the RPC errors raised in util.py
carry the server's response, never the request or its credentials.
"""
import json
import os
import tempfile
import time

import env

_sections: dict[str, dict] = {}


def _section(name: str) -> dict:
    return _sections.setdefault(name, {'errors_total': 0})


def set(name: str, **fields) -> None:
    _section(name).update(fields)


def ok(name: str, **fields) -> None:
    _section(name).update(fields, last_ok=int(time.time()))


def error(name: str, exc: BaseException) -> None:
    section = _section(name)
    section['errors_total'] += 1
    section['last_error_at'] = int(time.time())
    section['last_error'] = f'{type(exc).__name__}: {exc}'[:500]


def write(program: str) -> None:
    if not env.STATUS_DIR:
        return

    document = {'program': program, 'updated': int(time.time()), 'sections': _sections}

    try:
        fd, tmp = tempfile.mkstemp(dir=env.STATUS_DIR, prefix=f'.{program}.')
        with os.fdopen(fd, 'w') as f:
            json.dump(document, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(env.STATUS_DIR, f'{program}.json'))
    except OSError as e:
        # Monitoring must never take the forwarder down with it.
        print('Failed to write status file:', e)
