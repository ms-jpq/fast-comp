from asyncio import Queue, gather, wait
from itertools import chain
from traceback import format_exc
from typing import (
    Awaitable,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    cast,
)

from pynvim import Nvim

from .cache import make_cache
from .fuzzy import fuzzer
from .nvim import VimCompletion, call, print
from .types import (
    Factory,
    Notification,
    Position,
    Context,
    Settings,
    SourceFactory,
    SourceFeed,
    Step,
)

StepFunction = Callable[[SourceFeed], Awaitable[Sequence[Step]]]


def gen_context(line: str, col: int) -> Context:
    def is_sym(char: str) -> bool:
        return not char.isalnum() and not char.isspace()

    line_before = line[:col]
    line_after = line[col:]
    it = reversed(line_before)

    r_alnums: List[str] = []
    r_syms: List[str] = []
    for c in it:
        if c.isalnum():
            r_alnums.append(c)
        else:
            if is_sym(c):
                r_syms.append(c)
            break

    for c in it:
        if is_sym(c):
            r_syms.append(c)
        else:
            break

    alnums = "".join(reversed(r_alnums))
    syms = "".join(reversed(r_syms))
    return Context(
        line=line,
        line_before=line_before,
        line_after=line_after,
        alnums=alnums,
        syms=syms,
    )


async def gen_feed(nvim: Nvim) -> SourceFeed:
    def fed() -> SourceFeed:
        buffer = nvim.api.get_current_buf()
        filename = nvim.api.buf_get_name(buffer)
        filetype = nvim.api.buf_get_option(buffer, "filetype")
        window = nvim.api.get_current_win()
        row, col = nvim.api.win_get_cursor(window)
        line = nvim.api.get_current_line()
        position = Position(row=row, col=col)
        context = gen_context(line, col)
        return SourceFeed(
            filename=filename, filetype=filetype, position=position, context=context
        )

    return await call(nvim, fed)


async def manufacture(nvim: Nvim, factory: SourceFactory) -> Tuple[StepFunction, Queue]:
    chan: Queue = Queue()
    fact = cast(Factory, factory.manufacture)
    src = await fact(nvim, chan, factory.seed)

    async def source(feed: SourceFeed) -> Sequence[Step]:
        name = factory.name
        timeout = factory.timeout
        acc: List[Step] = []

        async def cont() -> None:
            async for comp in src(feed):
                normalized = comp.new_prefix.lower()
                completion = Step(
                    source=name,
                    source_shortname=factory.short_name,
                    priority=factory.priority,
                    normalized=normalized,
                    comp=comp,
                )
                acc.append(completion)

        done, pending = await wait((cont(),), timeout=timeout)
        await gather(*done)
        for p in pending:
            p.cancel()
        if pending:
            timeout_fmt = round(timeout * 1000)
            msg = (
                f"async completion source timed out - {name}, exceeded {timeout_fmt}ms"
            )
            await print(nvim, msg)
        return acc

    return source, chan


async def osha(
    nvim: Nvim, factory: SourceFactory
) -> Tuple[str, StepFunction, Optional[Queue]]:
    async def nil_steps(_: SourceFeed) -> Sequence[Step]:
        return ()

    try:
        step_fn, chan = await manufacture(nvim, factory=factory)
    except Exception as e:
        stack = format_exc()
        message = f"Error in source {factory.name}\n{stack}{e}"
        await print(nvim, message, error=True)
        return factory.name, nil_steps, None
    else:

        async def o_step(feed: SourceFeed) -> Sequence[Step]:
            try:
                return await step_fn(feed)
            except Exception as e:
                stack = format_exc()
                message = f"Error in source {factory.name}\n{stack}{e}"
                await print(nvim, message, error=True)
                return ()

        return factory.name, o_step, chan


async def merge(
    nvim: Nvim, chan: Queue, factories: Iterator[SourceFactory], settings: Settings
) -> Tuple[
    Callable[[bool], Awaitable[Tuple[Position, Iterator[VimCompletion]]]],
    Callable[[], Awaitable[None]],
]:
    facts = tuple(factories)
    limits = {fact.name: fact.limit for fact in facts}
    fuzzy = fuzzer(settings.fuzzy, limits=limits)
    src_gen = await gather(*(osha(nvim, factory=factory) for factory in facts))
    chans: Dict[str, Queue] = {name: chan for name, _, chan in src_gen}
    sources = tuple(source for _, source, _ in src_gen)

    push, retrieve = make_cache(settings.fuzzy)

    async def gen(force: bool) -> Tuple[Position, Iterator[VimCompletion]]:
        feed = await gen_feed(nvim)
        prefix = feed.context
        position = feed.position
        go = prefix.alnums or prefix.syms
        if go or force:
            cached, *comps = await gather(
                retrieve(feed), *(source(feed) for source in sources)
            )
            steps: Sequence[Step] = tuple((c for co in comps for c in co))
            push(feed, steps)
            completions = chain(steps, cached)
            return position, fuzzy(completions)
        else:
            return position, iter(())

    async def listen() -> None:
        while True:
            notif: Notification = await chan.get()
            source = notif.source
            ch = chans.get(source)
            if ch:
                await ch.put(notif.body)
            else:
                await print(
                    nvim, f"Notification to uknown source - {source}", error=True
                )

    return gen, listen
