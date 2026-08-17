import pytest

from caregrid import Sofa


def test_from_total_preserves_severity() -> None:
    sofa = Sofa.from_total(12)

    assert sofa.severity() == 12


def test_from_total_balances_fold() -> None:
    assert Sofa.from_total(12) == Sofa(2, 2, 2, 2, 2, 2)
    assert Sofa.from_total(13) == Sofa(3, 2, 2, 2, 2, 2)


def test_from_total_zero_and_max() -> None:
    assert Sofa.from_total(0) == Sofa(0, 0, 0, 0, 0, 0)
    assert Sofa.from_total(24) == Sofa(4, 4, 4, 4, 4, 4)


@pytest.mark.parametrize("total", [-1, 25])
def test_from_total_rejects_out_of_range(total: int) -> None:
    with pytest.raises(ValueError):
        Sofa.from_total(total)