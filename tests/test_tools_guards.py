

def test_task_create_refuses_junk_self_and_duplicates(monkeypatch):
    import tools, types
    created = []
    class B:
        def task_list(self, limit=600): return [{"id": 1, "title": "Weekly review", "status": "queued", "created_by": "coo", "created_at": 9e12}]
        def task_create(self, title, detail, owner, created_by, priority, source):
            created.append(title); return {"id": 2}
    monkeypatch.setattr(tools, "brain", B())
    monkeypatch.setattr(tools, "_agents", lambda: [types.SimpleNamespace(name=n) for n in ("coo", "tracker", "chief-of-staff")])
    assert "REFUSED" in tools.task_create("Draft follow-up email to unknown recipient", owner="chief-of-staff", _agent="tracker")
    assert "REFUSED" in tools.task_create("Create retry_failed_tasks.yaml", owner="coo", _agent="coo")
    assert "REFUSED" in tools.task_create("Fix thing", owner="coo", _agent="coo")
    assert "REFUSED" in tools.task_create("weekly review", owner="tracker", _agent="coo")
    assert "REFUSED" in tools.task_create("Ping", owner="nobody", _agent="coo")
    assert "queued" in tools.task_create("Update pipeline for Enablis", owner="tracker", _agent="coo") and created == ["Update pipeline for Enablis"]


def test_useful_lesson_filter():
    from runtime import useful_lesson
    assert not useful_lesson("Let's call strategy_list.")
    assert not useful_lesson("We need to call capital_positions.")
    assert not useful_lesson("NONE")
    assert not useful_lesson("Attempt to retrieve capital account data.")
    assert useful_lesson("Check strategy_list before recalling memories, because approval memories go stale and caused a wrong veto.")


def test_log_lead_refuses_placeholders_and_logs_real_leads(monkeypatch):
    import tools, types
    stored = []
    class B:
        def recall(self, q, limit=5, kind=None): return []
        def remember(self, content, **kw): stored.append((content, kw)); return types.SimpleNamespace(id=7)
    monkeypatch.setattr(tools, "brain", B())
    assert "REFUSED" in tools.log_lead("Best New Lead", "an AI chatbot for enquiries", "unknown", "https://x.com/p", 4)
    assert "REFUSED" in tools.log_lead("Hackney Lets", "AI enquiry assistant for a letting agent", "the owner", "peopleperhour", 4)
    assert "REFUSED" in tools.log_lead("Hackney Lets", "AI enquiry assistant for a letting agent", "the owner", "https://peopleperhour.com/job/1", 4)
    r = tools.log_lead("Hackney Lets", "AI enquiry assistant for a letting agent", "Sam Patel, owner", "https://peopleperhour.com/job/1", 4, 450, "peopleperhour", "today")
    assert r.startswith("lead #7") and stored[0][1]["kind"] == "lead" and "company:hackney-lets" in stored[0][1]["tags"]
    assert stored[0][1]["meta"]["contact"] == "Sam Patel, owner"


def test_schedule_followups_creates_dated_tasks_and_deal(monkeypatch):
    import tools, types, time
    created, updated, deals = [], [], []
    class B:
        def task_create(self, title, detail, owner, created_by, priority, source): created.append((title, owner, source)); return {"id": len(created)}
        def task_update(self, tid, agent, result): updated.append(result)
    monkeypatch.setattr(tools, "brain", B())
    import ceo
    monkeypatch.setattr(ceo, "deal_set", lambda aid, stage, note="": deals.append((aid, stage)))
    m = types.SimpleNamespace(id=42, tags=["approval", "approved", "proposal"], content="APPROVED from proposal-writer: proposal for Hackney Lets")
    tools.schedule_followups(m, "sam@hackneylets.co.uk", "AI enquiry assistant for Hackney Lets", "outbox/hackney.md")
    assert deals == [(42, "sent")] and [c[1] for c in created] == ["mail-assistant", "mail-assistant"]
    assert all("retry_after:" in u for u in updated)
    stamps = [int(u.split("retry_after:")[1]) for u in updated]
    assert stamps[0] > time.time() + 2.9 * 86400 and stamps[1] > time.time() + 6.9 * 86400
    # a plain reply is not a deal and gets no follow-ups
    created.clear(); deals.clear()
    tools.schedule_followups(types.SimpleNamespace(id=1, tags=["approval", "approved"], content="APPROVED: reply to recruiter about interview times"), "a@b.c", "Re: times", "outbox/x.md")
    assert not created and not deals


def test_post_variants_split_and_tool_requires_a_choice(monkeypatch, tmp_path):
    import tools, types
    text = "### Variant 1 – Hook\nFirst post body here.\nSecond line.\n\n---\n\n### Variant 2 – How\nSecond post body.\n\n### Variant 3 – Lesson\nThird post body.\n"
    v = tools.post_variants(text)
    assert v == ["First post body here.\nSecond line.", "Second post body.", "Third post body."]
    assert tools.post_variants("# Title\nJust one post.\n") == ["Just one post."]
    d = tmp_path / "posts"; d.mkdir(); f = d / "p.md"; f.write_text(text)
    monkeypatch.setattr(tools, "_safe", lambda p: f)
    m = types.SimpleNamespace(id=5, kind="approval", tags=["approved"], content="APPROVED: LinkedIn post file posts/p.md")
    monkeypatch.setattr(tools, "brain", types.SimpleNamespace(get=lambda i: m))
    assert "3 variants" in tools.linkedin_post(5, "posts/p.md")
    assert "variant must be" in tools.linkedin_post(5, "posts/p.md", 4)


def test_task_create_is_the_registered_tool_and_accepts_title():
    import tools
    t = tools.registry._tools["task_create"]
    fn = getattr(t, "fn", None) or getattr(t, "func", None) or t
    assert getattr(fn, "__name__", "") == "task_create"
