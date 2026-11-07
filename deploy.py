#!/usr/bin/env python3
"""Install custom_components/wiser_predictive on your HA box over ssh. Set HA_SSH, e.g.
  HA_SSH="ssh root@homeassistant.local" python3 -I deploy.py

  deploy.py            dry run: what would be new / changed / unchanged. Touches nothing.
  deploy.py --go       copy the files. Anything already on the box is backed up first. Verified by hash afterwards.
  deploy.py --restart  `ha core check`, then `ha core restart` (needed once for a new integration). Only on Peter's go-ahead.

Files on the box that are not in this repo are reported and never deleted.
Backup and the ledger row go to /tmp/wiser_predictive/ (apply-<run>.tsv, same columns as the other edit scripts).
"""
import argparse
import hashlib
import io
import os
import pathlib
import shlex
import subprocess
import sys
import tarfile
import time

SSH = os.environ.get("HA_SSH")  # command that runs a shell command on the HA box, e.g. "ssh root@homeassistant.local"
SRC = pathlib.Path(__file__).resolve().parent / "custom_components" / "wiser_predictive"
PARENT = "/config/custom_components"
DEST = PARENT + "/wiser_predictive"
LOG = pathlib.Path("/tmp/wiser_predictive")


def ssh(cmd, data=None, check=True):
    if not SSH:
        sys.exit('set HA_SSH to the command that runs a shell command on your HA box, e.g. HA_SSH="ssh root@homeassistant.local"')
    return subprocess.run(shlex.split(SSH) + [cmd], input=data, capture_output=True, check=check)


def local_files():
    return {
        str(p.relative_to(SRC)): p.read_bytes()
        for p in sorted(SRC.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def remote_hashes():
    out = ssh(
        f'cd {DEST} 2>/dev/null && find . -type f -not -path "*/__pycache__/*" -exec sha256sum {{}} + ; true'
    ).stdout.decode()
    found = {}
    for line in out.splitlines():
        digest, _, rel = line.partition("  ")
        found[rel[2:] if rel.startswith("./") else rel] = digest
    return found


def compare(local, remote):
    rows = []
    for rel, data in local.items():
        digest = hashlib.sha256(data).hexdigest()
        rows.append((rel, "new" if rel not in remote else "same" if remote[rel] == digest else "changed"))
    rows += [(rel, "box only (kept)") for rel in remote if rel not in local]
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()

    local = local_files()
    remote = remote_hashes()
    rows = compare(local, remote)
    print(f"{SRC}  ->  {DEST} on the box")
    for rel, verdict in rows:
        print(f"  {verdict:16} {rel}")

    if args.go:
        todo = [r for r, v in rows if v in ("new", "changed")]
        if not todo:
            print("nothing to copy")
        else:
            run = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            LOG.mkdir(parents=True, exist_ok=True)
            backup = ""
            if remote:
                backup = str(LOG / f"bak-{run}.tar")
                pathlib.Path(backup).write_bytes(ssh(f"tar c -C {PARENT} wiser_predictive").stdout)
                print("backup:", backup)
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                for rel in todo:
                    info = tarfile.TarInfo("wiser_predictive/" + rel)
                    info.size = len(local[rel])
                    info.mtime = int(time.time())
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(local[rel]))
            ssh(f"mkdir -p {PARENT} && tar x -C {PARENT}", data=buf.getvalue())
            after = remote_hashes()
            bad = [r for r, v in local.items() if after.get(r) != hashlib.sha256(v).hexdigest()]
            if bad:
                sys.exit(f"VERIFY FAILED, differs on the box: {bad}")
            print(f"copied {len(todo)} file(s), verified by hash")
            row = [run, "edit", "custom_components/wiser_predictive", "", f"installed {len(todo)} file(s) from pacmac/wiser_predictive", "0", "ok"]
            (LOG / f"apply-{run}.tsv").write_text("\t".join(row) + "\n")
            print("ledger row:", LOG / f"apply-{run}.tsv", "(record it from the ha-inventory repo)")
    elif not args.restart:
        print("dry run: nothing changed. Re-run with --go.")

    if args.restart:
        check = ssh("ha core check", check=False)
        print(check.stdout.decode() + check.stderr.decode())
        if check.returncode != 0:
            sys.exit("ha core check failed: not restarting")
        print("restarting HA core (a minute or two)...")
        ssh("ha core restart", check=False)


if __name__ == "__main__":
    main()
