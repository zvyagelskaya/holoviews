from collections import defaultdict

import numpy as np
import param

from bokeh.models import HoverTool

from ...core import util
from ..util import map_colors
from .element import ElementPlot, ColorbarPlot, line_properties, fill_properties
from .util import get_cmap, rgb2hex, expand_batched_style


class PathPlot(ElementPlot):

    show_legend = param.Boolean(default=False, doc="""
        Whether to show legend for the plot.""")

    style_opts = ['color'] + line_properties
    _plot_methods = dict(single='multi_line', batched='multi_line')
    _mapping = dict(xs='xs', ys='ys')
    _batched_style_opts = ['line_color', 'color', 'line_alpha', 'alpha',
                           'line_width', 'line_dash', 'line_join', 'line_cap']

    def _hover_opts(self, element):
        if self.batched:
            dims = list(self.hmap.last.kdims)
        else:
            dims = list(self.overlay_dims.keys())
        return dims, {}

    def get_data(self, element, ranges=None, empty=False):
        xidx, yidx = (1, 0) if self.invert_axes else (0, 1)
        xs = [] if empty else [path[:, xidx] for path in element.data]
        ys = [] if empty else [path[:, yidx] for path in element.data]
        return dict(xs=xs, ys=ys), dict(self._mapping)

    def get_batched_data(self, element, ranges=None, empty=False):
        data = defaultdict(list)

        zorders = self._updated_zorders(element)
        styles = self.lookup_options(element.last, 'style')
        styles = styles.max_cycles(len(self.ordering))

        for (key, el), zorder in zip(element.data.items(), zorders):
            self.overlay_dims = dict(zip(element.kdims, key))
            eldata, elmapping = self.get_data(el, ranges, empty)
            for k, eld in eldata.items():
                data[k].extend(eld)

            # Apply static styles
            nvals = len(list(eldata.values())[0])
            style = styles[zorder]
            expand_batched_style(style, self._batched_style_opts,
                                 data, elmapping, nvals, multiple=True)

        return data, elmapping


class PolygonPlot(ColorbarPlot, PathPlot):

    style_opts = ['color', 'cmap', 'palette'] + line_properties + fill_properties
    _plot_methods = dict(single='patches', batched='patches')
    _batched_style_opts = ['line_color', 'fill_color', 'color',
                           'fill_alpha', 'line_alpha', 'alpha', 'line_width',
                           'line_dash', 'line_join', 'line_cap']

    def _hover_opts(self, element):
        if self.batched:
            dims = list(self.hmap.last.kdims)
        else:
            dims = list(self.overlay_dims.keys())
        dims += element.vdims
        return dims, {}

    def get_data(self, element, ranges=None, empty=False):
        xs = [] if empty else [path[:, 0] for path in element.data]
        ys = [] if empty else [path[:, 1] for path in element.data]
        data = dict(xs=ys, ys=xs) if self.invert_axes else dict(xs=xs, ys=ys)

        style = self.style[self.cyclic_index]
        mapping = dict(self._mapping)

        if element.vdims and element.level is not None:
            cdim = element.vdims[0]
            cmapper = self._get_colormapper(cdim, element, ranges, style)
            data[cdim.name] = [] if empty else element.dimension_values(2)
            mapping['fill_color'] = {'field': cdim.name,
                                     'transform': cmapper}

        if any(isinstance(t, HoverTool) for t in self.state.tools):
            dim_name = util.dimension_sanitizer(element.vdims[0].name)
            for k, v in self.overlay_dims.items():
                dim = util.dimension_sanitizer(k.name)
                data[dim] = [v for _ in range(len(xs))]
            data[dim_name] = [element.level for _ in range(len(xs))]

        return data, mapping
