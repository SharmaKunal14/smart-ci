import pytest
from auth import issue


@pytest.mark.parametrize("role", ["buyer", "admin"])
def test_allowed(role, allowed_roles):
    assert role in allowed_roles
    # Unit scope is role membership; checkout tests the wire-format contract.
    assert role in issue(role).values()


def test_reject():
    with pytest.raises(ValueError):
        issue("anonymous")
