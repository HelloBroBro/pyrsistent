"""
Hypothesis-based tests for pvector.
"""

import gc

from collections import Iterable
from functools import wraps
from pyrsistent import PClass, field

from pytest import fixture

from pyrsistent import pvector, discard

from hypothesis import strategies as st, assume
from hypothesis.stateful import RuleBasedStateMachine, Bundle, rule


class TestObject(object):
    """
    An object that might catch reference count errors sometimes.
    """
    def __init__(self):
        self.id = id(self)

    def __repr__(self):
        return "<%s>" % (self.id,)

    def __del__(self):
        # If self is a dangling memory reference this check might fail. Or
        # segfault :)
        if self.id != id(self):
            raise RuntimeError()


@fixture(scope="module")
def gc_when_done(request):
    request.addfinalizer(gc.collect)


def test_setup(gc_when_done):
    """
    Ensure we GC when tests finish.
    """


# Pairs of a list and corresponding pvector:
PVectorAndLists = st.lists(st.builds(TestObject), average_size=5).map(
    lambda l: (l, pvector(l)))


def verify_inputs_unmodified(original):
    """
    Decorator that asserts that the wrapped function does not modify its
    inputs.
    """
    def to_tuples(pairs):
        return [(tuple(l), tuple(pv)) for (l, pv) in pairs]

    @wraps(original)
    def wrapper(self, **kwargs):
        inputs = [k for k in kwargs.values() if isinstance(k, Iterable)]
        tuple_inputs = to_tuples(inputs)
        try:
            return original(self, **kwargs)
        finally:
            # Ensure inputs were unmodified:
            assert to_tuples(inputs) == tuple_inputs
    return wrapper


def assert_equal(l, pv):
    assert l == pv
    assert len(l) == len(pv)
    length = len(l)
    for i in range(length):
        assert l[i] == pv[i]
    for i in range(length):
        for j in range(i, length):
            assert l[i:j] == pv[i:j]
    assert l == list(iter(pv))


class PVectorBuilder(RuleBasedStateMachine):
    """
    Build a list and matching pvector step-by-step.

    In each step in the state machine we do same operation on a list and
    on a pvector, and then when we're done we compare the two.
    """
    sequences = Bundle("sequences")

    @rule(target=sequences, start=PVectorAndLists)
    def initial_value(self, start):
        """
        Some initial values generated by a hypothesis strategy.
        """
        return start

    @rule(target=sequences, former=sequences)
    @verify_inputs_unmodified
    def append(self, former):
        """
        Append an item to the pair of sequences.
        """
        l, pv = former
        obj = TestObject()
        l2 = l[:]
        l2.append(obj)
        return l2, pv.append(obj)

    @rule(target=sequences, start=sequences, end=sequences)
    @verify_inputs_unmodified
    def extend(self, start, end):
        """
        Extend a pair of sequences with another pair of sequences.
        """
        l, pv = start
        l2, pv2 = end
        # compare() has O(N**2) behavior, so don't want too-large lists:
        assume(len(l) + len(l2) < 50)
        l3 = l[:]
        l3.extend(l2)
        return l3, pv.extend(pv2)

    @rule(target=sequences, former=sequences, choice=st.choices())
    @verify_inputs_unmodified
    def remove(self, former, choice):
        """
        Remove an item from the sequences.
        """
        l, pv = former
        assume(l)
        l2 = l[:]
        i = choice(range(len(l)))
        del l2[i]
        return l2, pv.delete(i)

    @rule(target=sequences, former=sequences, choice=st.choices())
    @verify_inputs_unmodified
    def set(self, former, choice):
        """
        Overwrite an item in the sequence.
        """
        l, pv = former
        assume(l)
        l2 = l[:]
        i = choice(range(len(l)))
        obj = TestObject()
        l2[i] = obj
        return l2, pv.set(i, obj)

    @rule(target=sequences, former=sequences, choice=st.choices())
    @verify_inputs_unmodified
    def transform_set(self, former, choice):
        """
        Transform the sequence by setting value.
        """
        l, pv = former
        assume(l)
        l2 = l[:]
        i = choice(range(len(l)))
        obj = TestObject()
        l2[i] = obj
        return l2, pv.transform([i], obj)

    @rule(target=sequences, former=sequences, choice=st.choices())
    @verify_inputs_unmodified
    def transform_discard(self, former, choice):
        """
        Transform the sequence by discarding a value.
        """
        l, pv = former
        assume(l)
        l2 = l[:]
        i = choice(range(len(l)))
        del l2[i]
        return l2, pv.transform([i], discard)

    @rule(target=sequences, former=sequences, choice=st.choices())
    @verify_inputs_unmodified
    def subset(self, former, choice):
        """
        A subset of the previous sequence.
        """
        l, pv = former
        assume(l)
        i = choice(range(len(l)))
        j = choice(range(len(l)))
        return l[i:j], pv[i:j]

    @rule(pair=sequences)
    @verify_inputs_unmodified
    def compare(self, pair):
        """
        The list and pvector must match.
        """
        l, pv = pair
        # compare() has O(N**2) behavior, so don't want too-large lists:
        assume(len(l) < 50)
        assert_equal(l, pv)


PVectorBuilderTests = PVectorBuilder.TestCase


class EvolverItem(PClass):
    original_list = field()
    original_pvector = field()
    current_list = field()
    current_evolver = field()


class PVectorEvolverBuilder(RuleBasedStateMachine):
    """
    Build a list and matching pvector evolver step-by-step.

    In each step in the state machine we do same operation on a list and
    on a pvector evolver, and then when we're done we compare the two.
    """
    sequences = Bundle("evolver_sequences")

    @rule(target=sequences, start=PVectorAndLists)
    def initial_value(self, start):
        """
        Some initial values generated by a hypothesis strategy.
        """
        l, pv = start
        return EvolverItem(original_list=l,
                           original_pvector=pv,
                           current_list=l[:],
                           current_evolver=pv.evolver())

    @rule(item=sequences)
    def append(self, item):
        """
        Append an item to the pair of sequences.
        """
        obj = TestObject()
        item.current_list.append(obj)
        item.current_evolver.append(obj)

    @rule(start=sequences, end=sequences)
    def extend(self, start, end):
        """
        Extend a pair of sequences with another pair of sequences.
        """
        # compare() has O(N**2) behavior, so don't want too-large lists:
        assume(len(start.current_list) + len(end.current_list) < 50)
        start.current_evolver.extend(end.current_list)
        start.current_list.extend(end.current_list)

    @rule(item=sequences, choice=st.choices())
    def delete(self, item, choice):
        """
        Remove an item from the sequences.
        """
        assume(item.current_list)
        i = choice(range(len(item.current_list)))
        del item.current_list[i]
        del item.current_evolver[i]

    @rule(item=sequences, choice=st.choices())
    def setitem(self, item, choice):
        """
        Overwrite an item in the sequence using ``__setitem__``.
        """
        assume(item.current_list)
        i = choice(range(len(item.current_list)))
        obj = TestObject()
        item.current_list[i] = obj
        item.current_evolver[i] = obj

    @rule(item=sequences, choice=st.choices())
    def set(self, item, choice):
        """
        Overwrite an item in the sequence using ``set``.
        """
        assume(item.current_list)
        i = choice(range(len(item.current_list)))
        obj = TestObject()
        item.current_list[i] = obj
        item.current_evolver.set(i, obj)

    @rule(item=sequences)
    def compare(self, item):
        """
        The list and pvector evolver must match.
        """
        item.current_evolver.is_dirty()
        # compare() has O(N**2) behavior, so don't want too-large lists:
        assume(len(item.current_list) < 50)
        # original object unmodified
        assert item.original_list == item.original_pvector
        # evolver matches:
        for i in range(len(item.current_evolver)):
            assert item.current_list[i] == item.current_evolver[i]
        # persistent version matches
        assert_equal(item.current_list, item.current_evolver.persistent())
        # original object still unmodified
        assert item.original_list == item.original_pvector


PVectorEvolverBuilderTests = PVectorEvolverBuilder.TestCase
