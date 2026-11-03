from __future__ import annotations

import pytest

from comictaggerlib.gtinvalidator import is_valid_gtin


@pytest.mark.parametrize("valid", ["12345670", "036000291452", "4006381333931", "10012345000017"])
def test_gtin_check_digits(valid):
    assert is_valid_gtin(valid)
    assert not is_valid_gtin(valid[:-1] + str((int(valid[-1]) + 1) % 10))


def test_gtin_format():
    assert is_valid_gtin(" 4006-381 333931 ")
    assert not is_valid_gtin("123")
    assert not is_valid_gtin("1234567x")
