import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))


def test_citation_and_results_guards():
    import research as R
    p = {"source": "arxiv", "id": "2610.00001", "title": "Memory for Agents", "authors": ["Ada Lovelace", "B Babbage"], "year": "2026", "url": "https://arxiv.org/abs/2610.00001"}
    bib = R.bib_entry(p); key = R.bib_key(p)
    assert key == "lovelace2026memory" and "@article{lovelace2026memory" in bib
    assert R.cite_check(f"as in \\cite{{{key}}} and [@{key}] but not \\cite{{ghost2020x}}", bib)["missing"] == ["ghost2020x"]
    res = {"baseline": {"acc": 0.712, "std": 0.011}, "ours": {"acc": 0.785}, "n": 2000}
    ok = R.results_check("# Results\nAccuracy rose from 71.2% to 78.5% (n=2,000, 3 seeds, std 0.011).", res)
    assert ok["ok"] and ok["numbers_claimed"] == 3          # 2,000 is skipped as a possible year, 3 as a single digit
    bad = R.results_check("## Results\nWe reach 91.0% accuracy.", res); assert bad["unbacked"] == ["91.0"]
    assert R.results_check("# Method\nwe use 5 layers", res)["has_results_section"] is False
    assert R.results_check("\\section{Results}\nAccuracy 78.5\\%.", res)["ok"]


def test_paper_build_refuses_unbacked_papers(tmp_path, monkeypatch):
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    monkeypatch.setattr(tools, "brain", store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()))
    ws = tmp_path / "ws"; monkeypatch.setattr(tools, "WORKSPACE", ws); monkeypatch.setattr(tools, "RESEARCH_DIR", ws / "research")
    d = ws / "research" / "agent-memory"; (d / "experiments").mkdir(parents=True)
    (d / "references.bib").write_text("@article{lovelace2026memory,\n title={x}\n}\n")
    (d / "paper.md").write_text("# Memory\n## Related Work\nSee [@lovelace2026memory].\n## Results\nOurs reaches 78.5% vs 71.2%.\n")
    chk = json.loads(tools.paper_check("agent-memory")); assert not chk["ok"] and "no logged experiment results" in chk["note"]
    assert tools.paper_build("agent-memory").startswith("refused")
    (d / "experiments" / "results.json").write_text(json.dumps({"ours": 0.785, "baseline": 0.712}))
    out = tools.experiment_log("agent-memory", "research/agent-memory/experiments/results.json", "two conditions, 3 seeds", _agent="experimenter")
    assert out.startswith("logged") and (d / "experiments" / "log.jsonl").exists()
    assert json.loads(tools.paper_check("agent-memory"))["ok"]
    (d / "paper.md").write_text("# Memory\n## Related Work\nSee [@lovelace2026memory] and [@nobody2021fake].\n## Results\n78.5% vs 71.2%.\n")
    assert json.loads(tools.paper_check("agent-memory"))["citations"]["missing"] == ["nobody2021fake"]


def test_research_lab_is_wired():
    import yaml, runtime as rt
    lab = [b for b in rt.list_agents() if b.office == "research"]
    assert {b.name for b in lab} == {"research-lead", "literature-scout", "novelty-analyst", "experimenter", "paper-writer", "peer-reviewer"}
    assert all(b.cloud_only and "research-publishing" in b.skills for b in lab)
    lead = next(b for b in lab if b.name == "research-lead"); assert set(lead.delegates) == {b.name for b in lab} - {"research-lead"}
    st = yaml.safe_load(open(ROOT / "office" / "standing-work.yaml")); assert {i["agent"] for i in st} >= {"research-lead", "novelty-analyst"}
    org = yaml.safe_load(open(ROOT / "office" / "org.yaml")); heads = {d["head"] for d in org["departments"]}
    assert "research-lead" in heads and all(h in {b.name for b in rt.list_agents()} for h in heads)


def test_hiring_is_a_proposal_pribin_approves(tmp_path, monkeypatch):
    import tools, store, runtime as rt
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", b)
    ad = tmp_path / "agents"; ad.mkdir(); monkeypatch.setattr(tools, "AGENTS_DIR", ad); monkeypatch.setattr(rt, "AGENTS_DIR", ad)
    monkeypatch.setattr(tools, "HIRES_DIR", tmp_path / "hires"); sf = tmp_path / "standing.yaml"; sf.write_text("[]\n"); monkeypatch.setattr(tools, "STANDING_FILE", sf)
    body = "You look after clients after a proposal is won: onboarding, check-ins, invoices drafted for approval. Process: brain_recall the client, read the proposal, draft the next message, request_approval. Report in 5 lines. Never send anything yourself."
    assert tools.propose_hire("client-success", "brand-sales", "d", ["brain_recall", "mail_send"], body, "weekly client check-ins", "keeps clients paying").startswith("refused: a new hire cannot")
    assert tools.propose_hire("client-success", "nowhere", "d", ["brain_recall"], body, "w", "why").startswith("refused: office")
    out = tools.propose_hire("client-success", "brand-sales", "Looks after won clients", ["brain_recall", "read_file", "draft_email", "request_approval"], body, "Weekly: check each active client, draft the check-in or invoice note.", "Won work must turn into repeat work.", _agent="coo")
    mid = int(out.split("approval #")[1].split()[0]); assert not (ad / "client-success.md").exists()
    assert tools.apply_hire(mid).startswith("refused")
    b.update(mid, tags=["approved", "hire", "agent:client-success"])
    assert tools.apply_hire(mid) == "hired: client-success installed with standing work" and rt.load_brief("client-success").office == "brand-sales"
    import yaml; assert yaml.safe_load(sf.read_text())[0]["agent"] == "client-success"


def test_board_pack_writes_the_weekly_file(tmp_path, monkeypatch):
    import ceo, tools, store, push
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    monkeypatch.setattr(tools, "brain", store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()))
    monkeypatch.setattr(ceo, "ROOT", tmp_path); (tmp_path / "office").mkdir(); (tmp_path / "office" / "org.yaml").write_text(open(ROOT / "office" / "org.yaml").read())
    monkeypatch.setattr(push, "send", lambda *a, **k: {"sent": 1}); monkeypatch.setattr(tools, "notify", lambda *a: "ok")
    r = ceo.board_pack(); text = (tmp_path / r["file"]).read_text()
    assert "# Board pack" in text and "## Money" in text and "Research Lab (head: research-lead)" in text


def test_overlap_check_flags_copied_passage_but_not_paraphrase():
    import research as R
    src = ("We propose a shared memory architecture in which each agent writes short factual notes after every task and "
           "retrieves the most relevant notes before acting, which reduces duplicated work across the team by a large margin.")
    copied = "Background. " + src + " Our setting differs in scale."
    para = ("Agents in our office record a brief note when a task ends and look up related notes first; this cut repeated effort.")
    bad = R.overlap_check(copied, {"2610.1": src})
    assert not bad["ok"] and bad["flagged"][0]["source"] == "2610.1" and bad["flagged"][0]["longest_run_words"] >= 20
    good = R.overlap_check(para, {"2610.1": src})
    assert good["ok"] and not good["flagged"]
    quoted = 'As they put it, "' + src + '" [@x].'
    assert R.overlap_check(quoted, {"2610.1": src})["ok"]


def test_quote_check_uses_search_and_flags_verbatim_hits():
    import research as R
    paper = ("# Title\nIntro text. Our office of forty two agents records every handoff between agents in a shared SQLite brain and "
             "we measure how recall latency changes the chance that the receiving agent continues correctly without asking again. "
             "Short line. Another distinctive sentence about measuring handoff fidelity in production logs of a small agent office.")
    calls = []
    def search(phrase):
        calls.append(phrase)
        return ["Blog: our office of forty two agents records every handoff between agents in a shared sqlite brain and we measure ..."] if "forty two" in phrase else []
    r = R.quote_check(paper, search=search, k=3)
    assert calls and not r["ok"] and r["flagged"][0]["sentence"].startswith("Our office of forty two")
    def nothing(phrase): return []
    assert R.quote_check(paper, search=nothing, k=3)["ok"]
    def broken(phrase): raise RuntimeError("rate limited")
    rr = R.quote_check(paper, search=broken, k=2)
    assert not rr["ok"] and rr["checked"] == 0 and rr["errors"]
