import json, sys, time, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"))


def test_parse_draft_reads_attachments_and_send_allowlists_them(tmp_path, monkeypatch):
    import mail
    d = mail.parse_draft("To: a@b.co\nSubject: Invoice\nAttach: finance/invoices/INV-2026-001-acme.pdf, applications/acme/cv.pdf\n\nHello\n")
    assert d["attachments"] == ["finance/invoices/INV-2026-001-acme.pdf", "applications/acme/cv.pdf"]
    monkeypatch.setattr(mail, "check_sendable", lambda to, s, b, allow_self=False: to)
    monkeypatch.setattr(mail, "address", lambda: "me@x.co"); monkeypatch.setattr(mail, "_password", lambda: "p")
    monkeypatch.setattr(mail, "SENT_LOG", tmp_path / "sent.jsonl")
    sent = []
    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def login(self, *a): pass
        def send_message(self, msg): sent.append(msg)
        def quit(self): pass
    root = Path(mail.__file__).resolve().parent.parent / "workspace" / "finance" / "invoices"; root.mkdir(parents=True, exist_ok=True)
    f = root / "INV-TEST-attach.pdf"; f.write_bytes(b"%PDF-1.4 test")
    try:
        r = mail.send("a@b.co", "Invoice", "body", factory=FakeSMTP, attachments=["finance/invoices/INV-TEST-attach.pdf"])
        assert r["attachments"] == ["INV-TEST-attach.pdf"] and any(p.get_filename() == "INV-TEST-attach.pdf" for p in sent[0].iter_attachments())
        import pytest
        with pytest.raises(mail.MailError):
            mail.send("a@b.co", "x", "body", factory=FakeSMTP, attachments=["../.env"])
        with pytest.raises(mail.MailError):
            mail.send("a@b.co", "x", "body", factory=FakeSMTP, attachments=["office/logs/events.jsonl"])
    finally:
        f.unlink()


def test_invoice_create_writes_file_ledger_and_approval(tmp_path, monkeypatch):
    import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path); monkeypatch.setattr(tools, "INVOICE_DIR", tmp_path / "finance" / "invoices"); monkeypatch.setattr(tools, "LEDGER", tmp_path / "finance" / "ledger.csv")
    written = {}
    monkeypatch.setattr(tools, "write_file", lambda rel, text: written.__setitem__(rel, text) or (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True) or (tmp_path / rel).write_text(text))
    monkeypatch.setattr(tools, "export_pdf", lambda rel: f"{rel[:-3]}.pdf")
    remembered = []
    class B:
        def get(self, i): return types.SimpleNamespace(id=i, content="Deal with Hackney Lets: won, £450")
        def remember(self, content, **kw): remembered.append((content, kw)); return types.SimpleNamespace(id=77)
    monkeypatch.setattr(tools, "brain", B())
    monkeypatch.setenv("INVOICE_ADDRESS", "1 Test St, London"); monkeypatch.setenv("INVOICE_PAYMENT_DETAILS", "Bank X 00-00-00 12345678")
    assert "refused" in tools.invoice_create(5, "Hackney Lets", [{"description": "AI enquiry assistant", "amount_gbp": 450}], _agent="trader")
    assert "REFUSED" in tools.invoice_create(5, "Unknown client", [{"description": "x", "amount_gbp": 450}], _agent="bookkeeper")
    assert "REFUSED" in tools.invoice_create(5, "Hackney Lets", [{"description": "", "amount_gbp": 450}], _agent="bookkeeper")
    r = tools.invoice_create(5, "Hackney Lets", [{"description": "AI enquiry assistant (setup)", "amount_gbp": 450}, {"description": "Training session", "amount_gbp": 50}],
                             client_email="sam@hackneylets.co.uk", _agent="bookkeeper")
    assert r.startswith("invoice INV-") and "approval #77" in r
    path = next(iter(written)); text = written[path]
    assert path.startswith("finance/invoices/INV-") and path.endswith("-hackney-lets.md")
    assert "**Total due** | **500.00**" in text and "Not VAT registered" in text and "Bank X" in text and "1 Test St" in text
    ledger = (tmp_path / "finance" / "ledger.csv").read_text().splitlines()
    assert ledger[0].startswith("date,type") and ",income,Hackney Lets," in ledger[1] and ",500.00,0,draft,5," in ledger[1]
    assert remembered[0][1]["kind"] == "approval" and "invoice" in remembered[0][1]["tags"] and remembered[0][1]["meta"]["client_email"] == "sam@hackneylets.co.uk"
    # second invoice gets the next number
    r2 = tools.invoice_create(6, "Other Co", [{"description": "Site", "amount_gbp": 300}], _agent="bookkeeper")
    n1 = r.split()[1]; n2 = r2.split()[1]; assert int(n2[-3:]) == int(n1[-3:]) + 1


def test_won_deal_queues_invoice_task(monkeypatch):
    import ceo
    created = []
    class B:
        def get(self, i): return types.SimpleNamespace(id=i, content="APPROVED from proposal-writer: proposal for Hackney Lets (GBP 450)", meta={}, tags=["approved"])
        def recent(self, **kw): return []
        def update(self, *a, **k): pass
        def remember(self, *a, **k): return types.SimpleNamespace(id=90)
        def task_list(self, limit=300): return []
        def task_create(self, title, detail, **kw): created.append((title, kw["owner"])); return {"id": 1}
    monkeypatch.setattr(ceo, "_brain", lambda: B())
    monkeypatch.setattr(ceo, "price_of", lambda c: 450.0)
    ceo.deal_set(12, "sent"); assert not created
    ceo.deal_set(12, "won"); assert created and created[0][1] == "bookkeeper" and created[0][0].startswith("Draft invoice for Hackney Lets")


def test_analytics_shape(monkeypatch):
    import ceo
    a = ceo.analytics(3)
    assert len(a["days"]) == 3 and len(a["tasks"]) == 3 and set(a["tasks"][0]) == {"day", "done", "failed"}
    assert "providers" in a["tokens"] and "acceptance" in a and "approval_latency_hours_median" in a
