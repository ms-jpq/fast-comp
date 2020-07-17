from typing import AsyncIterator

from pkgs.types import SourceCompletion, SourceSeed
from pynvim import Nvim


async def main(
    nvim: Nvim, seed: SourceSeed
) -> AsyncIterator[AsyncIterator[SourceCompletion]]:
    async def source() -> AsyncIterator[SourceCompletion]:
        yield SourceCompletion(text="paths_stub")
        yield SourceCompletion(text="paths_stub1")

    while True:
        yield source()