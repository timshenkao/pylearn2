"""Tests for space utilities."""
import numpy as np

import theano
from theano import config
from theano import tensor
from theano.sandbox.cuda import CudaNdarrayType

from pylearn2.space import Conv2DSpace
from pylearn2.space import CompositeSpace
from pylearn2.space import VectorSpace
from pylearn2.space import Space
from pylearn2.space import IndexSpace
from pylearn2.utils import function
import itertools


def test_np_format_as_vector2conv2D():
    vector_space = VectorSpace(dim=8*8*3, sparse=False)
    conv2d_space = Conv2DSpace(shape=(8, 8), num_channels=3,
                               axes=('b', 'c', 0, 1))
    data = np.arange(5*8*8*3).reshape(5, 8*8*3)
    rval = vector_space.np_format_as(data, conv2d_space)

    # Get data in a Conv2DSpace with default axes
    new_axes = conv2d_space.default_axes
    axis_to_shape = {'b': 5, 'c': 3, 0: 8, 1: 8}
    new_shape = tuple([axis_to_shape[ax] for ax in new_axes])
    nval = data.reshape(new_shape)
    # Then transpose
    nval = nval.transpose(*[new_axes.index(ax) for ax in conv2d_space.axes])
    assert np.all(rval == nval)


def test_np_format_as_conv2D2vector():
    vector_space = VectorSpace(dim=8*8*3, sparse=False)
    conv2d_space = Conv2DSpace(shape=(8, 8), num_channels=3,
                               axes=('b', 'c', 0, 1))
    data = np.arange(5*8*8*3).reshape(5, 3, 8, 8)
    rval = conv2d_space.np_format_as(data, vector_space)
    nval = data.transpose(*[conv2d_space.axes.index(ax)
                            for ax in conv2d_space.default_axes])
    nval = nval.reshape(5, 3 * 8 * 8)
    assert np.all(rval == nval)

    vector_space = VectorSpace(dim=8*8*3, sparse=False)
    conv2d_space = Conv2DSpace(shape=(8, 8), num_channels=3,
                               axes=('c', 'b', 0, 1))
    data = np.arange(5*8*8*3).reshape(3, 5, 8, 8)
    rval = conv2d_space.np_format_as(data, vector_space)
    nval = data.transpose(*[conv2d_space.axes.index(ax)
                            for ax in conv2d_space.default_axes])
    nval = nval.reshape(5, 3 * 8 * 8)
    assert np.all(rval == nval)


def test_np_format_as_conv2D2conv2D():
    conv2d_space1 = Conv2DSpace(shape=(8, 8), num_channels=3,
                                axes=('c', 'b', 1, 0))
    conv2d_space0 = Conv2DSpace(shape=(8, 8), num_channels=3,
                                axes=('b', 'c', 0, 1))
    data = np.arange(5*8*8*3).reshape(5, 3, 8, 8)
    rval = conv2d_space0.np_format_as(data, conv2d_space1)
    nval = data.transpose(1, 0, 3, 2)
    assert np.all(rval == nval)


def test_np_format_as_conv2D_vector_conv2D():
    conv2d_space1 = Conv2DSpace(shape=(8, 8), num_channels=3,
                                axes=('c', 'b', 1, 0))
    vector_space = VectorSpace(dim=8*8*3, sparse=False)
    conv2d_space0 = Conv2DSpace(shape=(8, 8), num_channels=3,
                                axes=('b', 'c', 0, 1))
    data = np.arange(5*8*8*3).reshape(5, 3, 8, 8)

    vecval = conv2d_space0.np_format_as(data, vector_space)
    rval1 = vector_space.np_format_as(vecval, conv2d_space1)
    rval2 = conv2d_space0.np_format_as(data, conv2d_space1)
    assert np.allclose(rval1, rval2)

    nval = data.transpose(1, 0, 3, 2)
    assert np.allclose(nval, rval1)


def test_np_format_as_composite_composite():

    def make_composite_space(image_space):
        return CompositeSpace((CompositeSpace((image_space,)*2),
                               VectorSpace(dim=1)))

    shape = np.array([8, 11])
    channels = 3
    datum_size = channels * shape.prod()

    composite_topo = make_composite_space(Conv2DSpace(shape=shape,
                                                      num_channels=channels))
    composite_flat = make_composite_space(VectorSpace(dim=datum_size))

    def make_flat_data(batch_size, space):
        if isinstance(space, CompositeSpace):
            return tuple(make_flat_data(batch_size, subspace)
                         for subspace in space.components)
        else:
            assert isinstance(space, VectorSpace)
            return np.random.rand(batch_size, space.dim)

    batch_size = 5
    flat_data = make_flat_data(batch_size, composite_flat)
    composite_flat.np_validate(flat_data)

    topo_data = composite_flat.np_format_as(flat_data, composite_topo)
    composite_topo.np_validate(topo_data)
    new_flat_data = composite_topo.np_format_as(topo_data, composite_flat)

    def get_shape(batch):
        if isinstance(batch, np.ndarray):
            return batch.shape
        else:
            return tuple(get_shape(b) for b in batch)

    def batch_equals(batch_0, batch_1):
        assert type(batch_0) == type(batch_1)
        if isinstance(batch_0, tuple):
            if len(batch_0) != len(batch_1):
                return False

            return np.all(tuple(batch_equals(b0, b1)
                                for b0, b1 in zip(batch_0, batch_1)))
        else:
            assert isinstance(batch_0, np.ndarray)
            return np.all(batch_0 == batch_1)

    assert batch_equals(new_flat_data, flat_data)


def test_vector_to_conv_c01b_invertible():

    """
    Tests that the format_as methods between Conv2DSpace
    and VectorSpace are invertible for the ('c', 0, 1, 'b')
    axis format.
    """

    rng = np.random.RandomState([2013, 5, 1])

    batch_size = 3
    rows = 4
    cols = 5
    channels = 2

    conv = Conv2DSpace([rows, cols],
                       channels=channels,
                       axes=('c', 0, 1, 'b'))
    vec = VectorSpace(conv.get_total_dimension())

    X = conv.make_batch_theano()
    Y = conv.format_as(X, vec)
    Z = vec.format_as(Y, conv)

    A = vec.make_batch_theano()
    B = vec.format_as(A, conv)
    C = conv.format_as(B, vec)

    f = function([X, A], [Z, C])

    X = rng.randn(*(conv.get_origin_batch(batch_size).shape)).astype(X.dtype)
    A = rng.randn(*(vec.get_origin_batch(batch_size).shape)).astype(A.dtype)

    Z, C = f(X, A)

    np.testing.assert_allclose(Z, X)
    np.testing.assert_allclose(C, A)


def test_broadcastable():
    v = VectorSpace(5).make_theano_batch(batch_size=1)
    np.testing.assert_(v.broadcastable[0])
    c = Conv2DSpace((5, 5), channels=3,
                    axes=['c', 0, 1, 'b']).make_theano_batch(batch_size=1)
    np.testing.assert_(c.broadcastable[-1])
    d = Conv2DSpace((5, 5), channels=3,
                    axes=['b', 0, 1, 'c']).make_theano_batch(batch_size=1)
    np.testing.assert_(d.broadcastable[0])

def test_compare_index():
    dims = [5, 5, 5, 6]
    max_labels = [10, 10, 9, 10]
    index_spaces = [IndexSpace(dim=dim, max_labels=max_label)
                    for dim, max_label in zip(dims, max_labels)]
    assert index_spaces[0] == index_spaces[1]
    assert not any(index_spaces[i] == index_spaces[j]
                   for i, j in itertools.combinations([1, 2, 3], 2))
    vector_space = VectorSpace(dim=5)
    conv2d_space = Conv2DSpace(shape=(8, 8), num_channels=3,
                               axes=('b', 'c', 0, 1))
    composite_space = CompositeSpace((index_spaces[0],))
    assert not any(index_space == vector_space for index_space in index_spaces)
    assert not any(index_space == composite_space for index_space in index_spaces)
    assert not any(index_space == conv2d_space for index_space in index_spaces)


def test_np_format_as_index2vector():
    # Test 5 random batches for shape, number of non-zeros
    for _ in xrange(5):
        max_labels = np.random.randint(2, 10)
        batch_size = np.random.randint(1, 10)
        labels = np.random.randint(1, 10)
        batch = np.random.random_integers(max_labels - 1,
                                          size=(batch_size, labels))
        index_space = IndexSpace(dim=labels, max_labels=max_labels)
        vector_space_merge = VectorSpace(dim=max_labels)
        vector_space_concatenate = VectorSpace(dim=max_labels * labels)
        merged = index_space.np_format_as(batch, vector_space_merge)
        concatenated = index_space.np_format_as(batch, vector_space_concatenate)
        if batch_size > 1:
            assert merged.shape == (batch_size, max_labels)
            assert concatenated.shape == (batch_size, max_labels * labels)
        else:
            assert merged.shape == (max_labels,)
            assert concatenated.shape == (max_labels * labels,)
        assert np.count_nonzero(merged) <= batch.size
        assert np.count_nonzero(concatenated) == batch.size
        assert np.all(np.unique(concatenated) == np.array([0, 1]))
    # Make sure Theano variables give the same result
    batch = tensor.lmatrix('batch')
    single = tensor.lvector('single')
    batch_size = np.random.randint(2, 10)
    np_batch = np.random.random_integers(max_labels - 1,
                                         size=(batch_size, labels))
    np_single = np.random.random_integers(max_labels - 1,
                                          size=(labels))
    f_batch_merge = theano.function(
        [batch], index_space._format_as(batch, vector_space_merge)
    )
    f_batch_concatenate = theano.function(
        [batch], index_space._format_as(batch, vector_space_concatenate)
    )
    f_single_merge = theano.function(
        [single], index_space._format_as(single, vector_space_merge)
    )
    f_single_concatenate = theano.function(
        [single], index_space._format_as(single, vector_space_concatenate)
    )
    np.testing.assert_allclose(
        f_batch_merge(np_batch),
        index_space.np_format_as(np_batch, vector_space_merge)
    )
    np.testing.assert_allclose(
        f_batch_concatenate(np_batch),
        index_space.np_format_as(np_batch, vector_space_concatenate)
    )
    np.testing.assert_allclose(
        f_single_merge(np_single),
        index_space.np_format_as(np_single, vector_space_merge)
    )
    np.testing.assert_allclose(
        f_single_concatenate(np_single),
        index_space.np_format_as(np_single, vector_space_concatenate)
    )
