"""Delta-encoded market boards: periodic full checkpoints plus field-level deltas between them.

Why this exists. A full board snapshot is ~276 KB compressed (2,818 markets, off-season), and at the
capture cadence that projects to ~4.9 GB/season -- a floor, against GitHub's ~1 GB guidance. But
between two boards four minutes apart only 9 of 2,818 markets moved (0.32%). Almost the entire cost
is rewriting prices that did not change.

Design rules, each of which is a requirement rather than a preference:

* **Existing full snapshots are checkpoints, unchanged.** Deltas are a NEW ledger kind. Nothing
  already on the archive is rewritten, re-encoded or deleted, and a reader that knows only about
  full snapshots keeps working exactly as before. That is also why reconstruction resolves its base
  from the ordinary ``kalshi/markets`` kind: every board ever captured is already a valid base.
* **Reconstruction is deterministic and fail-closed.** A board is checkpoint + an unbroken,
  hash-chained, contiguously numbered run of deltas. Any gap, reordering, conflicting duplicate or
  content mismatch raises; it never returns a half-applied board, because a silently-wrong
  historical price is worse than no price.
* **Historical truth, not current truth.** Reconstruction at ``t`` reads only artifacts observed at
  or before ``t``. Nothing later can influence the answer, so settlement, evaluation and research
  keep seeing the board as it was.
* **Provenance survives compression.** The exact capture instant and run id of every tick live in
  the delta header and are restamped onto reconstructed rows, so a reconstructed snapshot is equal
  to the real one *field for field*, including the ledger's own stamps -- not merely equivalent.

The ledger stamps ``_observed_at_utc`` and ``_run_id`` onto every row, and they change every tick.
Diffing them would mark all 2,818 markets as changed and defeat the whole exercise. They are
snapshot-level facts rather than per-market data, so they are excluded from the diff and the board
hash, carried once in the delta header, and restamped on the way out. That is the one subtlety in
this module and the reason ``canonical_board`` exists.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .delta_timeutil import iso, parse_iso

SCHEMA = "kalshi.board.delta/1"

# Stamped per row by the ledger, identical across every row of one snapshot, and different on every
# snapshot. Excluded from the diff and the hash; carried in the delta header instead.
LEDGER_STAMPS = ("_observed_at_utc", "_run_id")

# The ledger kinds. Checkpoints deliberately reuse the pre-existing kind, so every board already on
# the archive is a usable base and no migration is needed.
CHECKPOINT_KIND = "kalshi/markets"
DELTA_KIND = "kalshi/markets_delta"
ORDERBOOK_CHECKPOINT_KIND = "kalshi/orderbooks"
ORDERBOOK_DELTA_KIND = "kalshi/orderbooks_delta"


class DeltaChainError(RuntimeError):
    """A delta chain is incomplete, out of order, duplicated or does not hash as recorded.

    Always fatal by design: reconstruction fails closed rather than returning a board it cannot
    prove. Callers must not catch this and continue with a partial board.
    """


def _canon(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, stable across runs and platforms."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_board(rows: Iterable[dict[str, Any]], key: str = "ticker") -> dict[str, dict[str, Any]]:
    """``{key: row}`` with ledger stamps stripped, ready to diff or hash.

    Rows without the key are dropped rather than silently merged under ``None`` -- a board is
    addressed by ticker, and a row that cannot be addressed cannot be reconstructed either.
    """
    board: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = r.get(key)
        if k is None:
            continue
        board[str(k)] = {f: v for f, v in r.items() if f not in LEDGER_STAMPS}
    return board


def market_digest(row: dict[str, Any]) -> str:
    """Canonical hash of one market's fields."""
    return hashlib.sha256(_canon(row).encode()).hexdigest()


def _compose(digests: dict[str, str]) -> str:
    return hashlib.sha256(_canon([[t, digests[t]] for t in sorted(digests)]).encode()).hexdigest()


def board_sha256(board: dict[str, dict[str, Any]]) -> str:
    """Canonical hash of a whole board. The unit of integrity for the entire scheme.

    Composed from per-market digests rather than from one serialisation of the whole board, so that
    chain verification can be INCREMENTAL: applying a delta only re-digests the markets it actually
    touched instead of re-serialising all ~2,800 every step. On a 24-delta chain of real boards that
    is the difference between ~2.1s and a fraction of it, and the determinism guarantee is unchanged
    -- the same board always yields the same digest, independent of insertion order.
    """
    return _compose({t: market_digest(r) for t, r in board.items()})


class BoardHash:
    """Running board hash that only re-digests markets a delta touched."""

    def __init__(self, board: dict[str, dict[str, Any]]) -> None:
        self._d = {t: market_digest(r) for t, r in board.items()}

    def touch(self, board: dict[str, dict[str, Any]], tickers: Iterable[str]) -> None:
        for t in tickers:
            row = board.get(t)
            if row is None:
                self._d.pop(t, None)
            else:
                self._d[t] = market_digest(row)

    def hexdigest(self) -> str:
        return _compose(self._d)


@dataclass(frozen=True)
class Delta:
    """One tick, expressed against the board immediately before it."""

    schema: str
    captured_at_utc: str
    run_id: str
    seq: int
    base_path: str
    base_sha256: str
    base_captured_at_utc: str
    parent_board_sha256: str
    board_sha256: str
    n_markets_before: int
    n_markets_after: int
    added: dict[str, dict[str, Any]] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    changed: dict[str, dict[str, Any]] = field(default_factory=dict)
    cleared: dict[str, list[str]] = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        return (_canon(asdict(self)) + "\n").encode()

    @staticmethod
    def from_bytes(raw: bytes) -> Delta:
        d = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
        known = set(Delta.__dataclass_fields__)
        missing = known - set(d)
        if missing:
            raise DeltaChainError(f"delta payload is missing required fields: {sorted(missing)}")
        return Delta(**{k: v for k, v in d.items() if k in known})

    @property
    def n_changed(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed) + len(self.cleared)


def diff_boards(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Field-level difference between two canonical boards.

    Four categories, because three would lose information: ``added`` and ``removed`` carry ticker
    lifecycle (a newly discovered market, a delisted one), ``changed`` carries new and updated field
    values, and ``cleared`` carries fields that disappeared from a row. Without ``cleared``, a field
    dropping out of a market's payload would be invisible and reconstruction would keep a stale
    value forever.
    """
    added = {t: dict(r) for t, r in after.items() if t not in before}
    removed = sorted(t for t in before if t not in after)
    changed: dict[str, dict[str, Any]] = {}
    cleared: dict[str, list[str]] = {}
    for t, new_row in after.items():
        old_row = before.get(t)
        if old_row is None:
            continue
        diff = {f: v for f, v in new_row.items() if f not in old_row or old_row[f] != v}
        gone = sorted(f for f in old_row if f not in new_row)
        if diff:
            changed[t] = diff
        if gone:
            cleared[t] = gone
    return {"added": added, "removed": removed, "changed": changed, "cleared": cleared}


def apply_delta(board: dict[str, dict[str, Any]], d: Delta) -> dict[str, dict[str, Any]]:
    """Apply one delta to a canonical board, returning a new board. Never mutates the input.

    Order matters and is fixed: removals, then additions, then field updates, then field clears.
    Any other order can make a tick that both removes and re-adds a ticker ambiguous.
    """
    out = {t: dict(r) for t, r in board.items()}
    for t in d.removed:
        out.pop(t, None)
    for t, row in d.added.items():
        out[t] = dict(row)
    for t, diff in d.changed.items():
        if t not in out:
            raise DeltaChainError(
                f"delta seq {d.seq} changes ticker {t!r}, which is not on the board -- the chain is "
                f"missing an earlier delta that added it"
            )
        out[t].update(diff)
    for t, fields in d.cleared.items():
        if t not in out:
            raise DeltaChainError(f"delta seq {d.seq} clears fields on absent ticker {t!r}")
        for f in fields:
            out[t].pop(f, None)
    return out


def apply_delta_in_place(board: dict[str, dict[str, Any]], d: Delta) -> set[str]:
    """Apply a delta by mutating ``board``; return the tickers touched.

    Used only by ``verify_chain``, which owns its working copy. Copying the whole board on every
    step is O(markets x chain length) for no benefit once the caller owns the buffer -- the public
    ``apply_delta`` keeps the pure, copying behaviour for everyone else.
    """
    touched: set[str] = set()
    for t in d.removed:
        board.pop(t, None)
        touched.add(t)
    for t, row in d.added.items():
        board[t] = dict(row)
        touched.add(t)
    for t, diff in d.changed.items():
        if t not in board:
            raise DeltaChainError(
                f"delta seq {d.seq} changes ticker {t!r}, which is not on the board -- the chain is "
                f"missing an earlier delta that added it"
            )
        board[t].update(diff)
        touched.add(t)
    for t, fields in d.cleared.items():
        if t not in board:
            raise DeltaChainError(f"delta seq {d.seq} clears fields on absent ticker {t!r}")
        for f in fields:
            board[t].pop(f, None)
        touched.add(t)
    return touched


def build_delta(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    *,
    captured_at: datetime,
    run_id: str,
    seq: int,
    base_path: str,
    base_sha256: str,
    base_captured_at: str,
) -> Delta:
    parts = diff_boards(before, after)
    return Delta(
        schema=SCHEMA,
        captured_at_utc=iso(captured_at),
        run_id=str(run_id),
        seq=int(seq),
        base_path=base_path,
        base_sha256=base_sha256,
        base_captured_at_utc=base_captured_at,
        parent_board_sha256=board_sha256(before),
        board_sha256=board_sha256(after),
        n_markets_before=len(before),
        n_markets_after=len(after),
        **parts,
    )


def dedupe_and_order(deltas: list[Delta]) -> list[Delta]:
    """Order a chain by seq, collapsing idempotent retries and rejecting real conflicts.

    A worker that retries a push can legitimately land the *same* delta twice; that is harmless and
    is collapsed. Two *different* deltas claiming the same seq is corruption -- the chain has forked
    and there is no way to know which branch history took -- so it fails closed.
    """
    by_seq: dict[int, Delta] = {}
    for d in deltas:
        prior = by_seq.get(d.seq)
        if prior is None:
            by_seq[d.seq] = d
            continue
        if prior == d:
            continue  # byte-identical retry
        raise DeltaChainError(
            f"two different deltas both claim seq {d.seq}: board hashes "
            f"{prior.board_sha256[:12]} and {d.board_sha256[:12]}; the chain has forked"
        )
    return [by_seq[s] for s in sorted(by_seq)]


def verify_chain(
    base_board: dict[str, dict[str, Any]],
    deltas: list[Delta],
    *,
    base_sha256: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Apply a whole chain, checking every link. Raises ``DeltaChainError`` on any defect.

    Checks, in order: the base hashes as the first delta expects; sequence numbers are contiguous
    from 1 with no gaps; capture instants strictly increase; each delta's recorded parent matches
    the running board; and each delta's recorded result matches what applying it actually produces.

    The last two are the ones that catch silent corruption -- a delta whose *content* was altered
    still has to reproduce its recorded ``board_sha256``.
    """
    ordered = dedupe_and_order(deltas)
    running = {t: dict(r) for t, r in base_board.items()}
    hasher = BoardHash(running)
    running_hash = hasher.hexdigest()

    if base_sha256 is not None and base_sha256 != running_hash:
        raise DeltaChainError(
            f"checkpoint board hashes to {running_hash[:12]} but {base_sha256[:12]} was expected"
        )

    expected_seq = 1
    previous_at: datetime | None = None
    for d in ordered:
        if d.schema != SCHEMA:
            raise DeltaChainError(f"delta seq {d.seq} has unknown schema {d.schema!r}")
        if d.seq != expected_seq:
            raise DeltaChainError(
                f"delta chain has a gap: expected seq {expected_seq}, found {d.seq}. "
                f"Refusing to reconstruct from an incomplete chain."
            )
        if d.parent_board_sha256 != running_hash:
            raise DeltaChainError(
                f"delta seq {d.seq} expects parent board {d.parent_board_sha256[:12]} but the chain "
                f"is at {running_hash[:12]} -- a delta is missing, altered or out of order"
            )
        at = parse_iso(d.captured_at_utc)
        if previous_at is not None and at <= previous_at:
            raise DeltaChainError(
                f"delta seq {d.seq} is stamped {d.captured_at_utc}, not after its predecessor "
                f"{iso(previous_at)} -- capture instants must strictly increase"
            )
        touched = apply_delta_in_place(running, d)
        hasher.touch(running, touched)
        running_hash = hasher.hexdigest()
        if running_hash != d.board_sha256:
            raise DeltaChainError(
                f"delta seq {d.seq} applied to {d.parent_board_sha256[:12]} yields "
                f"{running_hash[:12]} but records {d.board_sha256[:12]} -- the delta is corrupt"
            )
        if len(running) != d.n_markets_after:
            raise DeltaChainError(
                f"delta seq {d.seq} yields {len(running)} markets but records {d.n_markets_after}"
            )
        previous_at = at
        expected_seq += 1
    return running


def restamp(board: dict[str, dict[str, Any]], observed_at_utc: str, run_id: str) -> list[dict[str, Any]]:
    """Turn a canonical board back into ledger rows, restoring the stamps for that tick.

    This is what makes a reconstructed snapshot comparable to a real one field for field rather than
    merely equivalent: the stamps come from the delta header, so they are the true values for that
    capture instant, not the reconstruction's own clock.
    """
    out = []
    for _t, row in sorted(board.items()):
        r = dict(row)
        r["_observed_at_utc"] = observed_at_utc
        r["_run_id"] = run_id
        out.append(r)
    return out


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Read a gzip-JSONL snapshot."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
