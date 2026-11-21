import pytest


@pytest.fixture
def allowed_roles() -> set[str]:
    return {"buyer", "admin"}
