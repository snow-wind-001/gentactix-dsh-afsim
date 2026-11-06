"""Bound native settlement frames; all arithmetic stays in WSF Script.

4096 is a code-generation budget, not an advertised AFSIM interpreter limit.
Large flat callbacks retain thousands of platform references until return. The
closed compiler template can instead settle actors in the same order, with typed
scratch scalars shared by synchronous helpers and reset at the original time.
"""
import re

VERSION = 'actor-settlement-frames-1'
MAX_FLAT_LOCALS = 4096
PREFIX = 'gtx_settlement_'
_PROTECTED = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/')
_DECLARATION = re.compile(r'\b(double|int|bool|WsfPlatform)\s+([A-Za-z_]\w*)\s*(?==|;)')
_IDENTIFIER = re.compile(r'\b[A-Za-z_]\w*\b')


def _mask(text):
    return _PROTECTED.sub(lambda m: ' ' * len(m.group()), text)


def _declarations(text):
    return [(m[1], m[2]) for m in _DECLARATION.finditer(_mask(text))]


def _names(text):
    return set(_IDENTIFIER.findall(_mask(text)))


def _rewrite(text, shared):
    def code(value):
        value = _DECLARATION.sub(
            lambda m: m[2] if m[2] in shared else m.group(), value)
        return _IDENTIFIER.sub(
            lambda m: PREFIX + m.group() if m.group() in shared else m.group(), value)

    pieces = []
    last = 0
    for match in _PROTECTED.finditer(text):
        pieces.extend((code(text[last:match.start()]), match.group()))
        last = match.end()
    pieces.append(code(text[last:]))
    return ''.join(pieces)


def lower_settlement(header, actors, tail, *, max_flat_locals=MAX_FLAT_LOCALS):
    """Return (helper declarations, callback body, metadata), or preserve flat code.

    Fragments come from the compiler's actor boundaries, never arbitrary model
    text. Header objects are explicit helper parameters; scalars shared by actor
    bodies or goal aggregation retain their original types. Actor-local platform
    references cannot escape their frame. No equations or inputs are evaluated.
    """
    fragments = ['\n'.join(header), *('\n'.join(a) for a in actors), '\n'.join(tail)]
    declarations = [_declarations(text) for text in fragments]
    count = sum(len(items) for items in declarations)
    if count <= max_flat_locals:
        return None
    if not actors:
        raise ValueError('大型结算缺少单位代码边界')
    if any(name.startswith(PREFIX) for text in fragments for name in _names(text)):
        raise ValueError('结算暂存命名空间与生成模板冲突')

    definitions = {}
    for index, items in enumerate(declarations):
        for kind, name in items:
            definitions.setdefault(name, []).append((kind, index))
    references = [_names(text) for text in fragments]
    declared_names = [{name for _, name in items} for items in declarations]
    shared = {}
    for name, bindings in definitions.items():
        # Reused block-local names (e.g. sustainment's dt) remain private to
        # each helper. Only a read with no local declaration crosses a frame.
        external = [i for i, names in enumerate(references)
                    if name in names and name not in declared_names[i]]
        if not external:
            continue
        if len(bindings) != 1:
            raise ValueError('结算跨段变量重复声明：' + name)
        kind, owner = bindings[0]
        if owner == len(fragments) - 1:
            raise ValueError('结算前部引用尚未初始化的尾部变量：' + name)
        if kind == 'WsfPlatform':
            if owner != 0:
                raise ValueError('结算分段不可导出跨单位平台引用：' + name)
            continue
        shared[name] = kind

    prefix = ['script_variables']
    prefix += [f' {kind} {PREFIX}{name}=' + ('false' if kind == 'bool' else '0') + ';'
               for name, kind in shared.items()]
    prefix.append('end_script_variables')
    calls = []
    sizes = []
    header_objects = [(kind, name) for kind, name in declarations[0] if kind == 'WsfPlatform']
    for index, text in enumerate(fragments[1:-1]):
        parameters = [(kind, name) for kind, name in header_objects
                      if name in references[index + 1]]
        # Keep the hub available even when a particular actor has no pool work;
        # stable signatures make generated execution evidence easier to audit.
        if ('WsfPlatform', 'hub') in header_objects and ('WsfPlatform', 'hub') not in parameters:
            parameters.insert(0, ('WsfPlatform', 'hub'))
        function = f'GtxSettlementActor{index}'
        lowered = _rewrite(text, shared)
        prefix += [f'script void {function}(' + ','.join(f'{k} {n}' for k, n in parameters) + ')',
                   *lowered.splitlines(), 'end_script']
        calls.append(f' {function}(' + ','.join(n for _, n in parameters) + ');')
        sizes.append(len(_declarations(lowered)))
    body = [*_rewrite(fragments[0], shared).splitlines(), *calls,
            *_rewrite(fragments[-1], shared).splitlines()]
    return prefix, body, {'version': VERSION, 'actor_count': len(actors),
                         'flat_local_declarations': count, 'shared_scalars': len(shared),
                         'max_actor_locals': max(sizes, default=0)}
