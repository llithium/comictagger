"""Functions for validating the GTIN field"""

#
# Copyright 2012-2014 ComicTagger Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations


def is_valid_gtin(gtin: str) -> bool:
    """Check if the GTIN is valid.

    Args:
        gtin (str): The GTIN to validate.

    Returns:
        bool: True if the GTIN is valid, False otherwise.
    """
    gtin = gtin.strip().replace("-", "").replace(" ", "")

    if not gtin or len(gtin) not in (8, 12, 13, 14):
        return False

    try:
        digits = [int(d) for d in gtin]
    except ValueError:
        return False

    # The rightmost data digit has weight 3, regardless of GTIN length.
    control_number = sum(digit * (3 if i % 2 == 0 else 1) for i, digit in enumerate(reversed(digits[:-1])))
    control_number = (10 - (control_number % 10)) % 10

    return control_number == digits[-1]
