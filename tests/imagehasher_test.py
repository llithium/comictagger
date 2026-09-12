from __future__ import annotations

import math
import random
import statistics

import pytest
from PIL import Image

from comicapi.comicarchive import ComicArchive
from comictaggerlib.imagehasher import ImageHasher


def test_ahash(cbz: ComicArchive):
    md = cbz.read_tags("cr")
    covers = md.get_cover_page_index_list()
    assert covers
    cover = cbz.get_page(covers[0])
    assert cover

    ih = ImageHasher(data=cover)
    assert bin(212201432349720) == bin(ih.average_hash())


def test_dhash(cbz: ComicArchive):
    md = cbz.read_tags("cr")
    covers = md.get_cover_page_index_list()
    assert covers
    cover = cbz.get_page(covers[0])
    assert cover

    ih = ImageHasher(data=cover)
    assert bin(11278294082955047009) == bin(ih.difference_hash())


def test_phash(cbz: ComicArchive):
    md = cbz.read_tags("cr")
    covers = md.get_cover_page_index_list()
    assert covers
    cover = cbz.get_page(covers[0])
    assert cover

    ih = ImageHasher(data=cover)
    assert bin(15307782992485167995) == bin(ih.perception_hash())


# Golden values from the original full 32x32 DCT.
@pytest.mark.parametrize(
    "seed, expected",
    [
        (0, 17540969252830890744),
        (1, 9989304606940449625),
        (2, 9419382888505732894),
        (3, 15210222063336040157),
        (4, 9588227169596923566),
    ],
)
def test_phash_noise_compatibility(seed, expected):
    image = Image.frombytes("L", (32, 32), random.Random(seed).randbytes(1024))
    assert ImageHasher(image=image).perception_hash() == expected


@pytest.mark.parametrize("value", [0, 127, 255])
def test_phash_flat_compatibility(value):
    # Flat images amplify floating-point noise. Compare with the original full
    # transform on this platform instead of pinning platform-specific noise bits.
    def dct(values):
        result = []
        for k in range(32):
            total = 0.0
            for n in range(32):
                total += values[n] * math.cos(math.pi * k * (2 * n + 1) / 64)
            result.append(total)
        return result

    rows = [dct([value] * 32) for _ in range(32)]
    columns = [dct(column) for column in zip(*rows)]
    low = [columns[x][y] for y in range(8) for x in range(8)]
    median = statistics.median(low)
    expected = sum(1 << (63 - index) for index, coefficient in enumerate(low) if coefficient > median)
    assert ImageHasher(image=Image.new("L", (32, 32), value)).perception_hash() == expected
