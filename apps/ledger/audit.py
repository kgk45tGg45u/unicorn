"""The nightly audit of the UNIQ books (docs/08 section 5)."""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.core import audit as audit_log
from apps.core.hashing import chain_hash
from apps.core.sql import triggers_present

from .models import Account, AccountBalance, AuditRun, ChainHead, Entry, Transaction

APPEND_ONLY_TABLES = [
    "ledger_transaction",
    "ledger_entry",
    "core_auditevent",
    "rules_parameterchange",
    "members_signature",
    "members_vouch",
    "members_inpersoncheck",
    "votes_ballot",
    "votes_voterrecord",
    "ledger_dailyfingerprint",
    "tradefund_fundentry",
]


def _payload(tx, entries):
    return {
        "seq": tx.seq,
        "period": f"{tx.period.year}-{tx.period.month:02d}",
        "kind": tx.kind,
        "reason": tx.reason,
        "ref_type": tx.ref_type,
        "ref_id": tx.ref_id,
        "actor_ref": tx.actor_ref,
        "created_at": tx.created_at,
        "entries": [
            {"account": e.account_id, "amount": str(e.amount)} for e in sorted(entries, key=lambda e: e.account_id)
        ],
    }


def run_audit(full=False) -> AuditRun:
    started = timezone.now()
    last_ok = AuditRun.objects.filter(ok=True).order_by("-last_seq", "-started_at").first()
    start_seq = 0 if (full or last_ok is None) else last_ok.last_seq
    findings = []

    # 1 and 2: the chain links, the hashes, and every transaction sums to zero.
    prev_hash = "0" * 64
    if start_seq:
        previous = Transaction.objects.filter(seq=start_seq).first()
        if previous is None:
            findings.append(f"Transaction number {start_seq} from the last audit is missing.")
            start_seq = 0
        else:
            prev_hash = previous.hash
    entries_by_tx = defaultdict(list)
    for entry in Entry.objects.filter(transaction__seq__gt=start_seq).select_related("transaction"):
        entries_by_tx[entry.transaction_id].append(entry)
    last_seq, last_hash = start_seq, prev_hash
    expected_seq = start_seq + 1
    for tx in Transaction.objects.filter(seq__gt=start_seq).select_related("period").order_by("seq"):
        entries = entries_by_tx[tx.pk]
        if tx.seq != expected_seq:
            findings.append(f"Transaction numbers jump from {expected_seq - 1} to {tx.seq}.")
        expected_seq = tx.seq + 1
        if tx.prev_hash != last_hash:
            findings.append(f"Transaction {tx.seq} does not link to the one before it.")
        if chain_hash(tx.prev_hash, _payload(tx, entries)) != tx.hash:
            findings.append(f"Transaction {tx.seq} does not match its fingerprint.")
        if sum((e.amount for e in entries), Decimal("0")) != 0:
            findings.append(f"Transaction {tx.seq} does not add up to zero.")
        last_seq, last_hash = tx.seq, tx.hash

    head = ChainHead.objects.get(name="uniq")
    if (head.last_seq, head.last_hash) != (last_seq, last_hash):
        findings.append("The end of the chain does not match the last transaction.")

    # 3: every cached balance equals the sum of its entries.
    sums = {
        r["account"]: r["t"] for r in Entry.objects.values("account").annotate(t=Sum("amount")).values("account", "t")
    }
    balances = {b.account_id: b.balance for b in AccountBalance.objects.all()}
    for account_id in set(sums) | set(balances):
        if sums.get(account_id, Decimal("0")) != balances.get(account_id, Decimal("0")):
            findings.append(f"The saved balance of account {account_id} does not match its entries.")

    # 4: UNIQ outstanding = -(Fund 2).
    kinds = dict(Account.objects.values_list("id", "kind"))
    by_kind = defaultdict(lambda: Decimal("0"))
    for account_id, amount in sums.items():
        by_kind[kinds[account_id]] += amount
    if by_kind["member"] + by_kind["retirement"] + by_kind["fund1"] != -by_kind["fund2"]:
        findings.append("UNIQ outstanding does not equal minus the balance of Fund 2.")

    # 5: nobody is below zero.
    for account_id, amount in sums.items():
        if kinds[account_id] in ("member", "retirement") and amount < 0:
            findings.append(f"Account {account_id} is below zero.")

    # 6: the database triggers (a warning, the model guards still apply).
    for table, present in triggers_present(APPEND_ONLY_TABLES).items():
        if not present:
            findings.append(f"Warning: the table {table} has no database protection against changes.")

    # The trade fund's books (P08.T03): the chain, the hashes, and no holding below zero.
    from apps.tradefund import books

    findings.extend(books.audit_findings())

    # 7: (from P09) every closed period has its cancellation.

    run = AuditRun.objects.create(
        started_at=started,
        finished_at=timezone.now(),
        ok=not any(not f.startswith("Warning:") for f in findings),
        last_seq=last_seq,
        last_hash=last_hash,
        full=full or last_ok is None,
        findings=findings,
    )
    if not run.ok:
        audit_log.record("system", "audit_failed", run, findings=len(findings))
        from apps.tickets import briefs

        briefs.audit_failure(run)  # until auditors are elected (P07.T09), random confirmers look at it
    return run
