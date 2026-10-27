from harnesslab.core.tools import validate_args

SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}, "n": {"type": "integer"}},
    "required": ["path"],
    "additionalProperties": False,
}


def test_valid_args_have_no_problems():
    assert validate_args(SCHEMA, {"path": "a.py", "n": 2}) == []


def test_missing_required():
    assert validate_args(SCHEMA, {}) == ["missing required argument 'path'"]


def test_unknown_argument_rejected():
    assert validate_args(SCHEMA, {"path": "a", "mode": "w"}) == ["unknown argument 'mode'"]


def test_wrong_type():
    assert validate_args(SCHEMA, {"path": 3}) == ["argument 'path' must be string, got int"]


def test_bool_is_not_an_integer():
    assert validate_args(SCHEMA, {"path": "a", "n": True}) == [
        "argument 'n' must be integer, got boolean"
    ]


def test_non_object_args():
    assert validate_args(SCHEMA, ["a"]) == ["arguments must be a JSON object, got list"]
