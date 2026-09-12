"""A class to manage creating image content hashes, and calculate hamming distances"""

#
# Copyright 2013 ComicTagger Authors
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

import io
import logging
import math
import statistics
from statistics import median
from typing import TypeVar, cast

try:
    from PIL import Image

    pil_available = True
except ImportError:
    pil_available = False
logger = logging.getLogger(__name__)


_DCT_WEIGHTS = tuple(tuple(math.cos(math.pi * k * (2 * n + 1) / 64) for n in range(32)) for k in range(8))


class ImageHasher:
    def __init__(
        self,
        path: str | None = None,
        image: Image.Image | None = None,
        data: bytes = b"",
        width: int = 8,
        height: int = 8,
    ) -> None:
        self.width = width
        self.height = height

        if path is None and not data and not image:
            raise OSError

        if image is not None:
            self.image = image
            return

        try:
            if path is not None:
                self.image = Image.open(path)
            else:
                self.image = Image.open(io.BytesIO(data))
        except Exception:
            logger.exception("Image data seems corrupted!")
            # just generate a bogus image
            self.image = Image.new("L", (1, 1))

    def average_hash(self) -> int:
        try:
            image = self.image.resize((self.width, self.height), Image.Resampling.LANCZOS).convert("L")
        except Exception:
            logger.exception("average_hash error")
            return 0

        # This is always a float because of the .convert("L") above
        pixels = cast(tuple[float], image.get_flattened_data())
        avg = statistics.mean(pixels)

        h = 0
        for i, p in enumerate(pixels):
            if p > avg:
                h |= 1 << len(pixels) - 1 - i

        return h

    def difference_hash(self) -> int:
        try:
            image = self.image.resize((self.width + 1, self.height), Image.Resampling.LANCZOS).convert("L")
        except Exception:
            logger.exception("difference_hash error")
            return 0

        # This is always a float because of the .convert("L") above
        pixels = cast(tuple[float], image.get_flattened_data())
        h = 0
        z = (self.width * self.height) - 1
        for y in range(self.height):
            for x in range(self.width):
                idx = x + ((self.width + 1) * y)
                if pixels[idx] < pixels[idx + 1]:
                    h |= 1 << z
                z -= 1

        return h

    def perception_hash(self) -> int:
        """
        Pure python version of Perceptual Hash computation of https://github.com/JohannesBuchner/imagehash/tree/master
        Implementation follows http://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html
        """

        highfreq_factor = 4
        img_size = 8 * highfreq_factor

        try:
            image = self.image.convert("L").resize((img_size, img_size), Image.Resampling.LANCZOS)
        except Exception:
            logger.exception("p_hash error converting to greyscale and resizing")
            return 0

        # Compute only the 8x8 low-frequency block. Keep the original accumulation
        # order so floating-point rounding does not change the hash.
        pixels = cast(tuple[int, ...], image.get_flattened_data())
        rows = []
        for y in range(32):
            row = []
            for weights in _DCT_WEIGHTS:
                value = 0.0
                for x in range(32):
                    value += pixels[y * 32 + x] * weights[x]
                row.append(value)
            rows.append(row)
        dctlowfreq = []
        for weights in _DCT_WEIGHTS:
            for x in range(8):
                value = 0.0
                for y in range(32):
                    value += rows[y][x] * weights[y]
                dctlowfreq.append(value)
        med = median(dctlowfreq)

        h = 0
        for i, p in enumerate(dctlowfreq):
            if p > med:
                h |= 1 << len(dctlowfreq) - 1 - i

        return h

    # accepts 2 hashes (longs or hex strings) and returns the hamming distance

    T = TypeVar("T", int, str)

    @staticmethod
    def hamming_distance(h1: T, h2: T) -> int:
        if isinstance(h1, int):
            n1 = h1
        else:
            n1 = int(h1, 16)

        if isinstance(h2, int):
            n2 = h2
        else:
            n2 = int(h2, 16)

        # xor the two numbers
        n = n1 ^ n2
        return n.bit_count()
