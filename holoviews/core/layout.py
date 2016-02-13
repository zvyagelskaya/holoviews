"""
Supplies Pane, Layout, NdLayout and AdjointLayout. Pane extends View
to allow multiple Views to be presented side-by-side in a NdLayout. An
AdjointLayout allows one or two Views to be ajoined to a primary View
to act as supplementary elements.
"""

from functools import reduce
from itertools import chain

import numpy as np

import param

from .dimension import Dimension, Dimensioned, ViewableElement
from .ndmapping import OrderedDict, NdMapping, UniformNdMapping
from .tree import AttrTree
from .util import (int_to_roman, sanitize_identifier, group_sanitizer,
                   label_sanitizer, unique_array)
from . import traversal


class Composable(object):
    """
    Composable is a mix-in class to allow Dimensioned object to be
    embedded within Layouts and GridSpaces.
    """

    def __add__(self, obj):
        return Layout.from_values(self) + Layout.from_values(obj)


    def __lshift__(self, other):
        if isinstance(other, (ViewableElement, NdMapping)):
            return AdjointLayout([self, other])
        elif isinstance(other, AdjointLayout):
            return AdjointLayout(other.data.values()+[self])
        else:
            raise TypeError('Cannot append {0} to a AdjointLayout'.format(type(other).__name__))



class Empty(Dimensioned, Composable):
    """
    Empty may be used to define an empty placeholder in a Layout. It can be
    placed in a Layout just like any regular Element and container
    type via the + operator or by passing it to the Layout constructor
    as a part of a list.
    """

    group = param.String(default='Empty')

    def __init__(self):
        super(Empty, self).__init__(None)



class AdjointLayout(Dimensioned):
    """
    A AdjointLayout provides a convenient container to lay out a primary plot
    with some additional supplemental plots, e.g. an image in a
    Image annotated with a luminance histogram. AdjointLayout accepts a
    list of three ViewableElement elements, which are laid out as follows with
    the names 'main', 'top' and 'right':
     ___________ __
    |____ 3_____|__|
    |           |  |  1:  main
    |           |  |  2:  right
    |     1     |2 |  3:  top
    |           |  |
    |___________|__|
    """

    kdims = param.List(default=[Dimension('AdjointLayout')], constant=True)

    layout_order = ['main', 'right', 'top']

    _deep_indexable = True
    _auxiliary_component = False

    def __init__(self, data, **params):

        self.main_layer = 0 # The index of the main layer if .main is an overlay
        if data and len(data) > 3:
            raise Exception('AdjointLayout accepts no more than three elements.')

        if data is not None and all(isinstance(v, tuple) for v in data):
            data = dict(data)
        if isinstance(data, dict):
            wrong_pos = [k for k in data if k not in self.layout_order]
            if wrong_pos:
                raise Exception('Wrong AdjointLayout positions provided.')
        elif isinstance(data, list):
            data = dict(zip(self.layout_order, data))
        else:
            data = OrderedDict()

        super(AdjointLayout, self).__init__(data, **params)


    @property
    def group(self):
        if self.main and self.main.group != type(self.main).__name__:
            return self.main.group
        else:
            return 'AdjointLayout'

    @property
    def label(self):
        return self.main.label if self.main else ''


    # Both group and label need empty setters due to param inheritance
    @group.setter
    def group(self, group): pass
    @label.setter
    def label(self, label): pass


    def relabel(self, label=None, group=None, depth=1):
        # Identical to standard relabel method except for default depth of 1
        return super(AdjointLayout, self).relabel(label=label, group=group, depth=depth)


    def get(self, key, default=None):
        return self.data[key] if key in self.data else default


    def dimension_values(self, dimension, unique=False):
        dimension = self.get_dimension(dimension, strict=True).name
        return self.main.dimension_values(dimension, unique)


    def __getitem__(self, key):
        if key is ():
            return self

        data_slice = None
        if isinstance(key, tuple):
            data_slice = key[1:]
            key = key[0]

        if isinstance(key, int) and key <= len(self):
            if key == 0:  data = self.main
            if key == 1:  data = self.right
            if key == 2:  data = self.top
            if data_slice: data = data[data_slice]
            return data
        elif isinstance(key, str) and key in self.data:
            if data_slice is None:
                return self.data[key]
            else:
                self.data[key][data_slice]
        elif isinstance(key, slice) and key.start is None and key.stop is None:
            return self if data_slice is None else self.clone([el[data_slice]
                                                               for el in self])
        else:
            raise KeyError("Key {0} not found in AdjointLayout.".format(key))


    def __setitem__(self, key, value):
        if key in ['main', 'right', 'top']:
            if isinstance(value, (ViewableElement, UniformNdMapping)):
                self.data[key] = value
            else:
                raise ValueError('AdjointLayout only accepts Element types.')
        else:
            raise Exception('Position %s not valid in AdjointLayout.' % key)


    def __lshift__(self, other):
        views = [self.data.get(k, None) for k in self.layout_order]
        return AdjointLayout([v for v in views if v is not None] + [other])


    @property
    def ddims(self):
        return self.main.dimensions()

    @property
    def main(self):
        return self.data.get('main', None)

    @property
    def right(self):
        return self.data.get('right', None)

    @property
    def top(self):
        return self.data.get('top', None)

    @property
    def last(self):
        items = [(k, v.last) if isinstance(v, NdMapping) else (k, v)
                 for k, v in self.data.items()]
        return self.__class__(dict(items))


    def keys(self):
        return list(self.data.keys())


    def items(self):
        return list(self.data.items())


    def __iter__(self):
        i = 0
        while i < len(self):
            yield self[i]
            i += 1


    def __add__(self, obj):
        return Layout.from_values(self) + Layout.from_values(obj)


    def __len__(self):
        return len(self.data)



class NdLayout(UniformNdMapping):
    """
    NdLayout is a UniformNdMapping providing an n-dimensional
    data structure to display the contained Elements and containers
    in a layout. Using the cols method the NdLayout can be rearranged
    with the desired number of columns.
    """

    data_type = (ViewableElement, AdjointLayout, UniformNdMapping)

    def __init__(self, initial_items=None, **params):
        self._max_cols = 4
        self._style = None
        super(NdLayout, self).__init__(initial_items=initial_items, **params)


    @property
    def uniform(self):
        return traversal.uniform(self)


    @property
    def shape(self):
        num = len(self.keys())
        if num <= self._max_cols:
            return (1, num)
        nrows = num // self._max_cols
        last_row_cols = num % self._max_cols
        return nrows+(1 if last_row_cols else 0), min(num, self._max_cols)


    def grid_items(self):
        """
        Compute a dict of {(row,column): (key, value)} elements from the
        current set of items and specified number of columns.
        """
        if list(self.keys()) == []:  return {}
        cols = self._max_cols
        return {(idx // cols, idx % cols): (key, item)
                for idx, (key, item) in enumerate(self.data.items())}


    def cols(self, n):
        self._max_cols = n
        return self


    def __add__(self, obj):
        return Layout.from_values(self) + Layout.from_values(obj)


    @property
    def last(self):
        """
        Returns another NdLayout constituted of the last views of the
        individual elements (if they are maps).
        """
        last_items = []
        for (k, v) in self.items():
            if isinstance(v, NdMapping):
                item = (k, v.clone((v.last_key, v.last)))
            elif isinstance(v, AdjointLayout):
                item = (k, v.last)
            else:
                item = (k, v)
            last_items.append(item)
        return self.clone(last_items)


# To be removed after 1.3.0
class Warning(param.Parameterized): pass
collate_deprecation = Warning(name='Deprecation Warning')

class Layout(AttrTree, Dimensioned):
    """
    A Layout is an AttrTree with ViewableElement objects as leaf
    values. Unlike AttrTree, a Layout supports a rich display,
    displaying leaf items in a grid style layout. In addition to the
    usual AttrTree indexing, Layout supports indexing of items by
    their row and column index in the layout.

    The maximum number of columns in such a layout may be controlled
    with the cols method and the display policy is set with the
    display method. A display policy of 'auto' may use the string repr
    of the tree for large trees that would otherwise take a long time
    to display wheras a policy of 'all' will always display all the
    available leaves. The detailed settings for the 'auto' policy may
    be set using the max_branches option of the %output magic.
    """

    group = param.String(default='Layout', constant=True)

    _deep_indexable = True

    @classmethod
    def collate(cls, data, kdims=None, key_dimensions=None):
        kdims = key_dimensions if (kdims is None) else kdims
        if kdims is None:
            raise Exception("Please specify the key dimensions.")

        collate_deprecation.warning("Layout.collate will be deprecated after version 1.3.0."
                                    "\nUse HoloMap.collate instead (see HoloViews homepage for example usage)")
        from .element import Collator
        layouts = {k:(v if isinstance(v, Layout) else Layout.from_values([v]))
                      for k,v in data.items()}
        return Collator(layouts, kdims=kdims)()


    @classmethod
    def new_path(cls, path, item, paths, count):
        sanitizers = [sanitize_identifier, group_sanitizer, label_sanitizer]
        path = tuple(fn(p) for (p, fn) in zip(path, sanitizers))
        while any(path[:i] in paths or path in [p[:i] for p in paths]
                  for i in range(1,len(path)+1)):
            path = path[:2]
            pl = len(path)
            if (pl == 1 and not item.label) or (pl == 2 and item.label):
                new_path = path + (int_to_roman(count-1),)
                if path in paths:
                    paths[paths.index(path)] = new_path
                path = path + (int_to_roman(count),)
            else:
                path = path[:-1] + (int_to_roman(count),)
            count += 1
        return path, count


    @classmethod
    def relabel_item_paths(cls, items):
        """
        Given a list of path items (list of tuples where each element
        is a (path, element) pair), generate a new set of path items that
        guarantees that no paths clash. This uses the element labels as
        appropriate and automatically generates roman numeral
        identifiers if necessary.
        """
        paths, path_items = [], []
        count = 2
        for path, item in items:
            new_path, count = cls.new_path(path, item, paths, count)
            new_path = tuple(''.join((p[0].upper(), p[1:])) for p in new_path)
            path_items.append(item)
            paths.append(new_path)
        return list(zip(paths, path_items))


    @classmethod
    def _from_values(cls, val):
        return reduce(lambda x,y: x+y, val).display('auto')

    @classmethod
    def from_values(cls, val):
        """
        Returns a Layout given a list (or tuple) of viewable
        elements or just a single viewable element.
        """
        collection = isinstance(val, (list, tuple))
        if type(val) is cls:
            return val
        elif collection and len(val)>1:
            return cls._from_values(val)
        elif collection:
            val = val[0]
        group = group_sanitizer(val.group)
        group = ''.join([group[0].upper(), group[1:]])
        label = label_sanitizer(val.label if val.label else 'I')
        label = ''.join([label[0].upper(), label[1:]])
        return cls(items=[((group, label), val)])


    def __init__(self, items=None, identifier=None, parent=None, **kwargs):
        self.__dict__['_display'] = 'auto'
        self.__dict__['_max_cols'] = 4
        if items and all(isinstance(item, Dimensioned) for item in items):
            items = self.from_values(items).data
        params = {p: kwargs.pop(p) for p in list(self.params().keys())+['id'] if p in kwargs}
        AttrTree.__init__(self, items, identifier, parent, **kwargs)
        Dimensioned.__init__(self, self.data, **params)


    @property
    def uniform(self):
        return traversal.uniform(self)

    @property
    def shape(self):
        num = len(self)
        if num <= self._max_cols:
            return (1, num)
        nrows = num // self._max_cols
        last_row_cols = num % self._max_cols
        return nrows+(1 if last_row_cols else 0), min(num, self._max_cols)


    def relabel(self, label=None, group=None, depth=0):
        # Standard relabel method except _max_cols and _display transferred
        relabelled = super(Layout, self).relabel(label=label, group=group, depth=depth)
        relabelled.__dict__['_max_cols'] = self.__dict__['_max_cols']
        relabelled.__dict__['_display'] = self.__dict__['_display']
        return relabelled

    def clone(self, *args, **overrides):
        """
        Clone method for Layout matches Dimensioned.clone except the
        display mode is also propagated.
        """
        clone = super(Layout, self).clone(*args, **overrides)
        clone._display = self._display
        clone._cols = self._cols
        clone.id = self.id
        return clone


    def dimension_values(self, dimension, unique=False):
        "Returns the values along the specified dimension."
        dimension = self.get_dimension(dimension, strict=True).name
        all_dims = self.traverse(lambda x: [d.name for d in x.dimensions()])
        if dimension in chain.from_iterable(all_dims):
            values = [el.dimension_values(dimension) for el in self
                      if dimension in el.dimensions(label=True)]
            vals = np.concatenate(values)
            return unique_array(vals) if unique else vals
        else:
            return super(Layout, self).dimension_values(dimension, unique)


    def cols(self, ncols):
        self._max_cols = ncols
        return self


    def display(self, option):
        "Sets the display policy of the Layout before returning self"
        options = ['auto', 'all']
        if option not in options:
            raise Exception("Display option must be one of %s" %
                            ','.join(repr(el) for el in options))
        self._display = option
        return self


    def select(self, selection_specs=None, **selections):
        return super(Layout, self).select(selection_specs, **selections).display(self._display)


    def grid_items(self):
        return {tuple(np.unravel_index(idx, self.shape)): (path, item)
                for idx, (path, item) in enumerate(self.items())}


    def regroup(self, group):
        """
        Assign a new group string to all the elements and return a new
        Layout.
        """
        new_items = [el.relabel(group=group) for el in self.data.values()]
        return reduce(lambda x,y: x+y, new_items)


    def __getitem__(self, key):
        if isinstance(key, int):
            if key < len(self):
                return self.data.values()[key]
            raise KeyError("Element out of range.")
        if len(key) == 2 and not any([isinstance(k, str) for k in key]):
            if key == (slice(None), slice(None)): return self
            row, col = key
            idx = row * self._max_cols + col
            keys = list(self.data.keys())
            if idx >= len(keys) or col >= self._max_cols:
                raise KeyError('Index %s is outside available item range' % str(key))
            key = keys[idx]
        return super(Layout, self).__getitem__(key)


    def __len__(self):
        return len(self.data)


    def __add__(self, other):
        other = self.from_values(other)
        items = list(self.data.items()) + list(other.data.items())
        return Layout(items=self.relabel_item_paths(items)).display('all')



__all__ = list(set([_k for _k, _v in locals().items()
                    if isinstance(_v, type) and (issubclass(_v, Dimensioned)
                                                 or issubclass(_v, Layout))]))
