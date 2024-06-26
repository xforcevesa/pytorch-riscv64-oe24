# mypy: ignore-errors

MAX_CYCLE = 3000

import itertools
import operator

from typing import Dict, List, Optional

from .. import polyfill, variables
from ..exc import unimplemented

from .base import MutableLocal, VariableTracker
from .constant import ConstantVariable


class ItertoolsVariable(VariableTracker):
    def __init__(self, value, **kwargs):
        super().__init__(**kwargs)
        self.value = value

    def __repr__(self):
        return f"ItertoolsVariable({self.value})"

    def python_type(self):
        return type(self.value)

    def as_python_constant(self):
        return self.value

    def call_function(
        self, tx, args: "List[VariableTracker]", kwargs: "Dict[str, VariableTracker]"
    ) -> "VariableTracker":
        if (
            self.value is itertools.product
            and not kwargs
            and all(arg.has_unpack_var_sequence(tx) for arg in args)
        ):
            seqs = [arg.unpack_var_sequence(tx) for arg in args]
            items = []
            for item in itertools.product(*seqs):
                items.append(variables.TupleVariable(list(item)))
            return variables.ListIteratorVariable(items, mutable_local=MutableLocal())
        elif (
            self.value is itertools.chain
            and not kwargs
            and all(arg.has_unpack_var_sequence(tx) for arg in args)
        ):
            seqs = [arg.unpack_var_sequence(tx) for arg in args]
            items = list(itertools.chain.from_iterable(seqs))
            return variables.ListIteratorVariable(items, mutable_local=MutableLocal())
        elif self.value is itertools.accumulate:
            from .builtin import BuiltinVariable

            if any(key not in ["initial", "func"] for key in kwargs.keys()):
                unimplemented(
                    "Unsupported kwargs for itertools.accumulate: "
                    f"{','.join(set(kwargs.keys()) - {'initial', 'func'})}"
                )

            acc = kwargs.get("initial")

            if len(args) in [1, 2] and args[0].has_unpack_var_sequence(tx):
                seq = args[0].unpack_var_sequence(tx)

                if "func" in kwargs and len(args) == 1:
                    func = kwargs["func"].call_function
                elif len(args) == 2:
                    func = args[1].call_function
                elif len(args) == 1:
                    # Default to operator.add
                    func = BuiltinVariable(operator.add).call_function
                else:
                    unimplemented(
                        "itertools.accumulate can only accept one of: `func` kwarg, pos 2 arg"
                    )
            else:
                unimplemented("Unsupported arguments for itertools.accumulate")

            items = []
            if acc is not None:
                items.append(acc)
            for item in seq:
                if acc is None:
                    acc = item
                else:
                    try:
                        acc = func(tx, [acc, item], {})
                    except Exception:
                        raise unimplemented(  # noqa: TRY200
                            f"Unexpected failure in invoking function during accumulate. Failed running func {func}({item}{acc})"
                        )
                items.append(acc)

            return variables.ListIteratorVariable(items, mutable_local=MutableLocal())
        elif (
            self.value is itertools.combinations
            and not kwargs
            and len(args) == 2
            and args[0].has_unpack_var_sequence(tx)
            and args[1].is_python_constant()
        ):
            iterable = args[0].unpack_var_sequence(tx)
            r = args[1].as_python_constant()

            items = []
            for item in itertools.combinations(iterable, r):
                items.append(variables.TupleVariable(list(item)))
            return variables.ListIteratorVariable(items, mutable_local=MutableLocal())
        elif self.value is itertools.groupby:
            if any(kw != "key" for kw in kwargs.keys()):
                unimplemented(
                    "Unsupported kwargs for itertools.groupby: "
                    f"{','.join(set(kwargs.keys()) - {'key'})}"
                )

            def retrieve_const_key(key):
                if isinstance(key, variables.SymNodeVariable):
                    return key.evaluate_expr()
                elif isinstance(key, variables.ConstantVariable):
                    return key.as_python_constant()
                else:
                    raise unimplemented(
                        "Unsupported key type for itertools.groupby: " + str(type(key))
                    )

            if len(args) == 1 and args[0].has_unpack_var_sequence(tx):
                seq = args[0].unpack_var_sequence(tx)
                keyfunc = (
                    (
                        lambda x: (
                            retrieve_const_key(
                                kwargs.get("key").call_function(tx, [x], {})
                            )
                        )
                    )
                    if "key" in kwargs
                    else None
                )
            else:
                unimplemented("Unsupported arguments for itertools.groupby")

            result = []
            try:
                for k, v in itertools.groupby(seq, key=keyfunc):
                    result.append(
                        variables.TupleVariable(
                            [
                                variables.ConstantVariable.create(k)
                                if variables.ConstantVariable.is_literal(k)
                                else k,
                                variables.ListIteratorVariable(
                                    list(v), mutable_local=MutableLocal()
                                ),
                            ],
                            mutable_local=MutableLocal(),
                        )
                    )
            except Exception:
                raise unimplemented(  # noqa: TRY200
                    "Unexpected failure when calling itertools.groupby"
                )
            return variables.ListIteratorVariable(result, mutable_local=MutableLocal())
        elif self.value is itertools.repeat:
            if len(args) < 2:
                return variables.RepeatIteratorVariable(
                    *args, mutable_local=MutableLocal()
                )

            from .builder import SourcelessBuilder

            return tx.inline_user_function_return(
                SourcelessBuilder()(tx, polyfill.repeat), args, kwargs
            )
        elif self.value is itertools.count:
            return variables.CountIteratorVariable(*args, mutable_local=MutableLocal())
        elif self.value is itertools.cycle:
            return variables.CycleIteratorVariable(*args, mutable_local=MutableLocal())
        else:
            return super().call_function(tx, args, kwargs)


class IteratorVariable(VariableTracker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def next_variables(self, tx):
        unimplemented("abstract method, must implement")


class RepeatIteratorVariable(IteratorVariable):
    def __init__(self, item: VariableTracker, **kwargs):
        super().__init__(**kwargs)
        self.item = item

    # Repeat needs no mutation, clone self
    def next_variables(self, tx):
        return self.item, self


class CountIteratorVariable(IteratorVariable):
    def __init__(self, item: int = 0, step: int = 1, **kwargs):
        super().__init__(**kwargs)
        if not isinstance(item, VariableTracker):
            item = ConstantVariable.create(item)
        if not isinstance(step, VariableTracker):
            step = ConstantVariable.create(step)
        self.item = item
        self.step = step

    def next_variables(self, tx):
        assert self.mutable_local
        tx.output.side_effects.mutation(self)
        next_item = self.item.call_method(tx, "__add__", [self.step], {})
        self.item = next_item
        return self.item, self


class CycleIteratorVariable(IteratorVariable):
    def __init__(
        self,
        iterator: IteratorVariable,
        saved: List[VariableTracker] = None,
        saved_index: int = 0,
        item: Optional[VariableTracker] = None,
        **kwargs,
    ):
        if saved is None:
            saved = []
        super().__init__(**kwargs)
        self.iterator = iterator
        self.saved = saved
        self.saved_index = saved_index
        self.item = item

    def next_variables(self, tx):
        assert self.mutable_local

        if self.iterator is not None:
            try:
                new_item, _ = self.iterator.next_variables(tx)
                if len(self.saved) > MAX_CYCLE:
                    unimplemented(
                        "input iterator to itertools.cycle has too many items"
                    )
                tx.output.side_effects.mutation(self)
                self.saved.append(new_item)
                self.item = new_item
                if self.item is None:
                    return self.next_variables(tx)
                return self.item, self
            except StopIteration:
                self.iterator = None
                return self.next_variables(tx)
        elif len(self.saved) > 0:
            tx.output.side_effects.mutation(self)
            self.saved_index = (self.saved_index + 1) % len(self.saved)
            return self.item, self
        else:
            raise StopIteration
