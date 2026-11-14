import sys, json, pathlib
sys.path.insert(0, sys.argv[1])  # sa_main checkout (stdlib-only module, no network call made)
from alpha_engine import cfb_availability_archive as m
pin = json.loads(pathlib.Path(sys.argv[1], m.PIN_PATH).read_text())
payload = pathlib.Path(sys.argv[2]).read_bytes()
rows = m.load_rows(pin, payload)   # validates size and git blob sha1
res = m.audit_rows(rows, source_sha=pin["source_git_blob_sha1"])
print(json.dumps(res, indent=1, sort_keys=True))
