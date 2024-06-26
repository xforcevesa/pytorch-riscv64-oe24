import collections
import dataclasses
import enum
from typing import Any, Optional, Union

from torch._guards import ChainedSource, GuardSource, Source

from . import utils
from .bytecode_transformation import create_call_function, create_instruction
from .utils import enum_repr

# It shouldn't be supported to construct an NNModuleVariable inside an FSDP module,
# so those cases are omitted intentionally
_GUARD_SOURCE_NN_MODULE = {
    GuardSource.LOCAL: GuardSource.LOCAL_NN_MODULE,
    GuardSource.GLOBAL: GuardSource.GLOBAL_NN_MODULE,
    GuardSource.LOCAL_NN_MODULE: GuardSource.LOCAL_NN_MODULE,
    GuardSource.GLOBAL_NN_MODULE: GuardSource.GLOBAL_NN_MODULE,
}

_GUARD_SOURCE_FSDP_MODULE = {
    GuardSource.LOCAL: GuardSource.LOCAL_FSDP_MODULE,
    GuardSource.GLOBAL: GuardSource.GLOBAL_FSDP_MODULE,
    GuardSource.LOCAL_NN_MODULE: GuardSource.LOCAL_FSDP_MODULE,
    GuardSource.GLOBAL_NN_MODULE: GuardSource.GLOBAL_FSDP_MODULE,
    GuardSource.LOCAL_FSDP_MODULE: GuardSource.LOCAL_FSDP_MODULE,
    GuardSource.GLOBAL_FSDP_MODULE: GuardSource.GLOBAL_FSDP_MODULE,
}

_GUARD_SOURCE_NOT_NN_MODULE = {
    GuardSource.LOCAL: GuardSource.LOCAL,
    GuardSource.GLOBAL: GuardSource.GLOBAL,
    GuardSource.LOCAL_NN_MODULE: GuardSource.LOCAL,
    GuardSource.GLOBAL_NN_MODULE: GuardSource.GLOBAL,
    GuardSource.LOCAL_FSDP_MODULE: GuardSource.LOCAL,
    GuardSource.GLOBAL_FSDP_MODULE: GuardSource.GLOBAL,
}


def is_constant_source(source):
    if isinstance(source, ConstantSource):
        return True
    try:
        if source.guard_source() == GuardSource.CONSTANT:
            return True
    except NotImplementedError:
        pass

    return False


def reconstruct_getitem(
    source: Union["GetItemSource", "ODictGetItemSource"], codegen, index_is_slice
):
    source.base.reconstruct(codegen)
    if isinstance(source.index, Source):
        source.index.reconstruct(codegen)
    else:
        if index_is_slice:
            assert isinstance(source, GetItemSource)
            codegen.append_output(codegen.create_load_const(source.unpack_slice()))
        else:
            codegen.append_output(codegen.create_load_const(source.index))


@dataclasses.dataclass(frozen=True)
class LocalSource(Source):
    local_name: str
    cell_or_freevar: bool = False

    def reconstruct(self, codegen):
        codegen.append_output(codegen.create_load(self.local_name))

    def guard_source(self):
        return GuardSource.LOCAL

    def name(self):
        return f"L[{repr(self.local_name)}]"


@dataclasses.dataclass(frozen=True)
class SyntheticLocalSource(Source):
    local_name: str

    def reconstruct(self, codegen):
        codegen.append_output(codegen.create_load(self.local_name))

    def guard_source(self):
        return GuardSource.SYNTHETIC_LOCAL

    def name(self):
        return f"SYNTHETIC_LOCAL[{self.local_name!r}]"


@dataclasses.dataclass(frozen=True)
class RandomValueSource(Source):
    random_call_index: int

    def guard_source(self):
        return GuardSource.RANDOM_VALUE

    def reconstruct(self, codegen):
        codegen.append_output(codegen.create_load(codegen.tx.output.random_values_var))
        codegen.append_output(codegen.create_load_const(self.random_call_index))
        codegen.append_output(create_instruction("BINARY_SUBSCR"))

    def name(self):
        return f"random_value_{self.random_call_index}"


@dataclasses.dataclass(frozen=True)
class GlobalSource(Source):
    global_name: str

    def reconstruct(self, codegen):
        codegen.append_output(
            codegen.create_load_global(self.global_name, False, add=True)
        )

    def guard_source(self):
        return GuardSource.GLOBAL

    def name(self):
        return f"G[{repr(self.global_name)}]"


@dataclasses.dataclass(frozen=True)
class GlobalWeakRefSource(Source):
    global_name: str

    def reconstruct(self, codegen):
        codegen.append_output(
            codegen.create_load_global(self.global_name, True, add=True)
        )
        codegen.extend_output(create_call_function(0, False))

    def guard_source(self):
        return GuardSource.GLOBAL

    def name(self):
        return f"G[{repr(self.global_name)}]()"


@dataclasses.dataclass(frozen=True)
class AttrSource(ChainedSource):
    member: str
    get_static: bool = False

    def __post_init__(self):
        assert self.base, "Can't construct an AttrSource without a valid base source"
        if "." in self.member:
            member_parts = self.member.split(".")
            object.__setattr__(
                self, "base", AttrSource(self.base, ".".join(member_parts[:-1]))
            )
            object.__setattr__(self, "member", member_parts[-1])

    def reconstruct(self, codegen):
        self.base.reconstruct(codegen)
        codegen.extend_output(codegen.create_load_attrs(self.member))

    def guard_source(self):
        return self.base.guard_source()

    def name(self):
        if self.get_static:
            return f"inspect.getattr_static({self.base.name()}, {self.member!r})"
        elif not self.member.isidentifier():
            return f"getattr({self.base.name()}, {self.member!r})"
        return f"{self.base.name()}.{self.member}"


@dataclasses.dataclass(frozen=True)
class ParamBufferSource(AttrSource):
    def guard_source(self):
        return _GUARD_SOURCE_NN_MODULE[self.base.guard_source()]


# This source is intended to be used in places where a source is needed but it is expected
# that the symbol will be simplified out later on. Symbols with ephemeral sources are
# prioritized to be simplified out when e.g. compared against a symbol without an ephemeral
# source. Guarding on this source is an error.
#
# Example: During subclass view fake-ification, any close-over ViewFunc state should be
# symbolicized / fake-ified to avoid invalid specialization during view replay. This source
# is useful for symbols utilized in the middle of the view chain that are not expected to be
# present within the final view shape metadata.
@dataclasses.dataclass(frozen=True)
class EphemeralSource(Source):
    desc: Optional[str] = None

    def guard_source(self):
        return GuardSource.EPHEMERAL

    def name(self):
        return f"<ephemeral{': ' + self.desc if self.desc is not None else ''}>"

    def make_guard(self):
        raise NotImplementedError()

    def is_ephemeral(self):
        return True


class TensorProperty(enum.Enum):
    SIZE = 0
    STRIDE = 1
    STORAGE_OFFSET = 2

    def method_name(self):
        if self is TensorProperty.SIZE:
            return "size"
        elif self is TensorProperty.STRIDE:
            return "stride"
        elif self is TensorProperty.STORAGE_OFFSET:
            return "storage_offset"


@dataclasses.dataclass(frozen=True)
class TensorPropertySource(ChainedSource):
    prop: TensorProperty
    idx: Optional[int] = None  # None for STORAGE_OFFSET

    def __post_init__(self):
        assert self.base is not None
        if self.prop is TensorProperty.STORAGE_OFFSET:
            assert self.idx is None
        else:
            assert self.idx is not None

    def reconstruct(self, codegen):
        self.base.reconstruct(codegen)
        codegen.append_output(codegen.create_load_attr(self.prop.method_name()))
        if self.idx is not None:
            codegen.append_output(codegen.create_load_const(self.idx))
        codegen.extend_output(
            create_call_function(1 if self.idx is not None else 0, True)
        )

    def guard_source(self):
        return self.base.guard_source()

    def name(self):
        if self.prop is TensorProperty.SIZE:
            return f"{self.base.name()}.size()[{self.idx}]"
        elif self.prop is TensorProperty.STRIDE:
            return f"{self.base.name()}.stride()[{self.idx}]"
        elif self.prop is TensorProperty.STORAGE_OFFSET:
            assert self.idx is None
            return f"{self.base.name()}.storage_offset()"
        else:
            raise AssertionError(f"unhandled {self.prop}")


@dataclasses.dataclass(frozen=True)
class NegateSource(ChainedSource):
    def __post_init__(self):
        assert self.base is not None

    def reconstruct(self, codegen):
        raise NotImplementedError()

    def guard_source(self):
        return self.base.guard_source()

    def name(self):
        # NB: use method call so that function stripping regexes work
        return f"{self.base.name()}.__neg__()"


@dataclasses.dataclass(frozen=True)
class ConvertIntSource(ChainedSource):
    def __post_init__(self):
        assert self.base is not None

    def reconstruct(self, codegen):
        self.base.reconstruct(codegen)

    def guard_source(self):
        return self.base.guard_source()

    def name(self):
        return f"cast_symbool_to_symint_guardless({self.base.name()})"


@dataclasses.dataclass(frozen=True)
class DefaultsSource(ChainedSource):
    idx_key: Union[int, str]
    is_kw: bool = False
    field: str = dataclasses.field(init=False, repr=False, compare=False)
    _name: str = dataclasses.field(init=False, repr=False, compare=False)

    def __post_init__(self):
        assert (
            self.base
        ), "Base must be a valid source in order to properly track and guard this Defaults to its origin."
        if self.is_kw:
            assert isinstance(self.idx_key, str)
            object.__setattr__(self, "field", "__kwdefaults__")
            object.__setattr__(
                self, "_name", f"{self.base.name()}.{self.field}['{self.idx_key}']"
            )
        else:
            assert isinstance(self.idx_key, int)
            object.__setattr__(self, "field", "__defaults__")
            object.__setattr__(
                self, "_name", f"{self.base.name()}.{self.field}[{self.idx_key}]"
            )

    def reconstruct(self, codegen):
        self.base.reconstruct(codegen)
        codegen.extend_output(codegen.create_load_attrs(self.field))
        codegen.append_output(codegen.create_load_const(self.idx_key))
        codegen.append_output(create_instruction("BINARY_SUBSCR"))

    def guard_source(self):
        return self.base.guard_source()

    def name(self):
        return self._name


@dataclasses.dataclass(frozen=True)
class GetItemSource(ChainedSource):
    index: Any
    index_is_slice: bool = False

    def __post_init__(self):
        assert self.base is not None
        if isinstance(self.index, slice):
            # store the hashable version of the slice so the whole GetItemSource is hashable
            super().__setattr__("index", self.index.__reduce__())
            super().__setattr__("index_is_slice", True)

    def reconstruct(self, codegen):
        reconstruct_getitem(self, codegen, index_is_slice=self.index_is_slice)
        codegen.append_output(create_instruction("BINARY_SUBSCR"))

    def guard_source(self):
        return self.base.guard_source()

    def unpack_slice(self):
        assert self.index_is_slice
        slice_class, slice_args = self.index
        return slice_class(*slice_args)

    def name(self):
        # Index can be of following types
        # 1) ConstDictKeySource
        # 2) enum.Enum
        # 3) index is a slice - example 1:4
        # 4) index is a constant - example string, integer
        if isinstance(self.index, Source):
            if not isinstance(self.index, ConstDictKeySource):
                raise ValueError(
                    "GetItemSource index must be a constant, enum or ConstDictKeySource"
                )
            return f"{self.base.name()}[{self.index.name()}]"
        elif self.index_is_slice:
            return f"{self.base.name()}[{self.unpack_slice()!r}]"
        elif isinstance(self.index, enum.Enum):
            return f"{self.base.name()}[{enum_repr(self.index, self.guard_source().is_local())}]"
        else:
            return f"{self.base.name()}[{self.index!r}]"


@dataclasses.dataclass(frozen=True)
class ConstDictKeySource(GetItemSource):
    def is_dict_key(self):
        return True

    def reconstruct(self, codegen):
        codegen.load_import_from(utils.__name__, "dict_keys_getitem")
        self.base.reconstruct(codegen)
        codegen.append_output(codegen.create_load_const(self.index))
        codegen.extend_output(create_call_function(2, True))

    def name(self):
        # The list creation will be CSE'd by PyExprCSEPass
        return f"list({self.base.name()}.keys())[{self.index!r}]"


@dataclasses.dataclass(frozen=True)
class TupleIteratorGetItemSource(GetItemSource):
    def reconstruct(self, codegen):
        codegen.load_import_from(utils.__name__, "tuple_iterator_getitem")
        self.base.reconstruct(codegen)
        codegen.append_output(codegen.create_load_const(self.index))
        codegen.extend_output(create_call_function(2, True))

    def name(self):
        return f"___tuple_iterator_getitem({self.base.name()}, {self.index!r})"


@dataclasses.dataclass(frozen=True)
class TypeSource(ChainedSource):
    def __post_init__(self):
        assert self.base is not None

    def reconstruct(self, codegen):
        codegen.load_import_from("builtins", "type")
        self.base.reconstruct(codegen)
        codegen.extend_output(create_call_function(1, True))

    def guard_source(self):
        return self.base.guard_source()

    def name(self):
        return f"type({self.base.name()})"


@dataclasses.dataclass(frozen=True)
class ODictGetItemSource(ChainedSource):
    index: Any

    def __post_init__(self):
        assert self.base is not None

    def reconstruct(self, codegen):
        codegen.append_output(
            codegen._create_load_const(collections.OrderedDict.__getitem__)
        )
        reconstruct_getitem(self, codegen, index_is_slice=False)
        codegen.extend_output(create_call_function(2, True))

    def guard_source(self):
        return self.base.guard_source()

    def name(self):
        if isinstance(self.index, type):
            rep = f'__load_module("{self.index.__module__}").{self.index.__qualname__}'
            return f"___odict_getitem({self.base.name()}, {rep})"
        elif isinstance(self.index, Source):
            return f"___odict_getitem({self.base.name()}, {self.index.name()})"
        else:
            return f"___odict_getitem({self.base.name()}, {self.index!r})"


@dataclasses.dataclass(frozen=True)
class NNModuleSource(ChainedSource):
    def reconstruct(self, codegen):
        self.base.reconstruct(codegen)

    def guard_source(self):
        return _GUARD_SOURCE_NN_MODULE[self.base.guard_source()]

    def name(self):
        return self.base.name()


@dataclasses.dataclass(frozen=True)
class NotNNModuleSource(NNModuleSource):
    def guard_source(self):
        return _GUARD_SOURCE_NOT_NN_MODULE[self.base.guard_source()]


@dataclasses.dataclass(frozen=True)
class FSDPNNModuleSource(NNModuleSource):
    def guard_source(self):
        return _GUARD_SOURCE_FSDP_MODULE[self.base.guard_source()]


@dataclasses.dataclass(frozen=True)
class GlobalStateSource(Source):
    def name(self):
        return ""

    def guard_source(self):
        return GuardSource.GLOBAL


@dataclasses.dataclass(frozen=True)
class ConstantSource(Source):
    source_name: str

    def reconstruct(self, codegen):
        codegen.append_output(
            codegen.create_load_global(self.source_name, False, add=False)
        )

    def guard_source(self):
        return GuardSource.CONSTANT

    def name(self):
        return self.source_name

    def make_guard(self, fn):
        raise NotImplementedError()


@dataclasses.dataclass(frozen=True)
class NumpyTensorSource(ChainedSource):
    def name(self) -> str:
        return f"___from_numpy({self.base.name()})"

    def guard_source(self):
        return self.base.guard_source()

    def reconstruct(self, codegen):
        codegen.load_import_from("torch", "as_tensor")
        self.base.reconstruct(codegen)
        codegen.extend_output(create_call_function(1, True))


# This is a synthetic source that is associated with the singleton
# shape env guard we always register for all frames.  We get the actual
# guard contents from the ambient ShapeEnv
@dataclasses.dataclass(frozen=True)
class ShapeEnvSource(Source):
    def name(self):
        return ""

    def guard_source(self):
        return GuardSource.SHAPE_ENV


@dataclasses.dataclass(frozen=True)
class BackwardStateSource(Source):
    def name(self):
        return ""

    def guard_source(self):
        return GuardSource.BACKWARD_STATE


def is_from_local_source(source: Source, *, allow_cell_or_freevar=True):
    if isinstance(source, ChainedSource):
        return is_from_local_source(
            source.base, allow_cell_or_freevar=allow_cell_or_freevar
        )
    if not isinstance(source, LocalSource):
        return False
    if not allow_cell_or_freevar and source.cell_or_freevar:
        return False
    return True


# TODO: can probably write a generic "test this on everything in the chain"
# helper
def is_from_defaults(source: Source):
    if isinstance(source, DefaultsSource):
        return True
    if isinstance(source, ChainedSource):
        return is_from_defaults(source.base)
    return False
