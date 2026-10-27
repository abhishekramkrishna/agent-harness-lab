import pytest

from harnesslab.workspace.sandbox import TaskSpec


@pytest.fixture
def lru() -> TaskSpec:
    return TaskSpec.load("lru-recency")


@pytest.fixture
def slug() -> TaskSpec:
    return TaskSpec.load("slugify")
