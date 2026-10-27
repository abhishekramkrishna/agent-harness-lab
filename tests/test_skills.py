import json
import shutil
from pathlib import Path

from harnesslab.skillcheck import check, tokenize

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def test_the_shipped_pack_passes():
    report = check(SKILLS)
    assert report.ok, report.errors
    assert len(report.trigger) == len(list(SKILLS.glob("*/SKILL.md")))


def copy_pack(tmp_path: Path) -> Path:
    dst = tmp_path / "skills"
    shutil.copytree(SKILLS, dst)
    return dst


def test_missing_section_is_an_error(tmp_path):
    pack = copy_pack(tmp_path)
    p = pack / "ship-gate" / "SKILL.md"
    p.write_text(p.read_text().replace("## When not to use", "## Exceptions"))
    assert any("missing section '## When not to use'" in e for e in check(pack).errors)


def test_user_invoked_cannot_call_user_invoked(tmp_path):
    pack = copy_pack(tmp_path)
    p = pack / "ship-gate" / "SKILL.md"
    p.write_text(p.read_text() + "\nThen run `trace-autopsy` on every failure.\n")
    assert any("must not invoke another user-invoked" in e for e in check(pack).errors)


def test_duplicate_descriptions_collide(tmp_path):
    pack = copy_pack(tmp_path)
    src, dst = pack / "stop-conditions", pack / "stop-conditions-two"
    shutil.copytree(src, dst)
    p = dst / "SKILL.md"
    p.write_text(p.read_text().replace("name: stop-conditions", "name: stop-conditions-two"))
    assert any("overlap" in e for e in check(pack).errors)


def test_vague_description_fails_its_trigger_evals(tmp_path):
    pack = copy_pack(tmp_path)
    p = pack / "trace-autopsy" / "SKILL.md"
    text = p.read_text()
    start = text.index("description:")
    end = text.index("\n", start)
    p.write_text(text[:start] + "description: Helps with agents. Use when needed." + text[end:])
    errors = check(pack).errors
    assert any(e.startswith("trace-autopsy: ranked #") for e in errors)


def test_negative_owner_must_exist(tmp_path):
    pack = copy_pack(tmp_path)
    ev = pack / "ship-gate" / "evals.json"
    data = json.loads(ev.read_text())
    data["trigger"]["negative"][0]["owner"] = "no-such-skill"
    ev.write_text(json.dumps(data))
    assert any("unknown" in e for e in check(pack).errors)


def test_tokenize_stems_and_drops_stopwords():
    assert tokenize("The agents were running tests") == ["agent", "were", "runn", "test"]
