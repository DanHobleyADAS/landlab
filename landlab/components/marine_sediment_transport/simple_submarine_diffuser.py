#! /usr/bin/env python
import numpy as np
from landlab.components import LinearDiffuser


_TINY_DIFFUSIVITY = 1.0e-20


class SimpleSubmarineDiffuser(LinearDiffuser):
    """
    Transport marine sediment using a water-depth-dependent diffusion model.

    This component models sediment transport as a diffusion process with a
    coefficient that depends on water depth :math:`h` as follows:

    .. math::
        D(h) = D_0 f_1(h) f_2(h)

    Here :math:`D_0` is the maximum value, corresponding to the input
    parameter :code:`shallow_water_diffusivity`.

    The function :math:`f_1(h)` describes the decrease in transport efficiency
    below the wave base depth :math:`h_w`. It is defined as unity for depth
    above the wave base, and as

    .. math::
        f_1(h) = \exp( -(h - h_w) / h_w)

    for :math:`h > h_w`.

    The function :math:`f_2(h)` handles the transition in transport efficiency
    around the shoreline. If :code:`tidal_range`, :math:`R_t`, is zero, then
    :math:`f_2` is set to unity underwater (:math:`h \ge 0`), and a tiny value
    above water (not zero, because that would cause a divide-by-zero error in
    the base class).
    If :math:`R_t > 0`, then a :math:`tanh` function is used to model
    a smooth decrease in :math:`D` from the low to high tide level:

    .. math::
        f_2(h) = (\tanh ( -h / R_t) + 1) / 2

    with an addition tiny value added to locations above water to avoid
    division by zero.
    """

    _name = "SimpleSubmarineDiffuser"

    _time_units = "y"

    _info = {
        "sea_level__elevation": {
            "dtype": "float",
            "intent": "in",
            "optional": False,
            "units": "m",
            "mapping": "grid",
            "doc": "Position of sea level",
        },
        "topographic__elevation": {
            "dtype": "float",
            "intent": "inout",
            "optional": False,
            "units": "m",
            "mapping": "node",
            "doc": "land and ocean bottom elevation, positive up",
        },
        "water__depth": {
            "dtype": "float",
            "intent": "out",
            "optional": False,
            "units": "m",
            "mapping": "node",
            "doc": "depth of water under current sea level"
        },
        "sediment_deposit__thickness": {
            "dtype": "float",
            "intent": "out",
            "optional": False,
            "units": "m",
            "mapping": "node",
            "doc": "Thickness of deposition or erosion",
        },
    }

    def __init__(
        self,
        grid,
        sea_level=0.0,
        wave_base=60.0,
        shallow_water_diffusivity=100.0,
        tidal_range=2.0,
        **kwds
    ):
        """
        Parameters
        ----------
        grid: ModelGrid (RasterModelGrid, HexModelGrid, etc.)
            A landlab grid.
        sea_level: float, optional
            The current sea level (m) (default 0)
        wave_base: float, optional
            Wave base (m) (default 60)
        shallow_water_diffusivity: float, optional
            Diffusivity coefficient for shallow water (m2 / y) (default 100)
        tidal_range: float, optional
            Tidal range (m) (default 2)
         """
        self._wave_base = float(wave_base)
        self._sea_level = sea_level
        grid.at_grid["sea_level__elevation"] = sea_level
        self._sea_level = grid.at_grid["sea_level__elevation"]
        self._shallow_water_diffusivity = shallow_water_diffusivity
        self._tidal_range = tidal_range
        if tidal_range > 0.0:
            self._inverse_tidal_range = 1.0 / tidal_range

        if not "kd" in grid.at_node:
            grid.add_zeros("kd", at="node")
        if not "sediment_deposit__thickness" in grid.at_node:
            grid.add_zeros("sediment_deposit__thickness", at="node")
        if "water__depth" in grid.at_node:
            self._depth = grid.at_node["water__depth"]
        else:
            self._depth = grid.add_zeros("water__depth", at="node")

        self._time = 0.0

        kwds.setdefault("linear_diffusivity", "kd")
        super(SimpleSubmarineDiffuser, self).__init__(grid, **kwds)

    @property
    def wave_base(self):
        return self._wave_base

    @wave_base.setter
    def wave_base(self, value):
        self._wave_base = float(value)

    @property
    def shallow_water_diffusivity(self):
        return self._shallow_water_diffusivity

    @shallow_water_diffusivity.setter
    def shallow_water_diffusivity(self, value):
        self._shallow_water_diffusivity = float(value)

    @property
    def time(self):
        return self._time

    @property
    def sea_level(self):
        return self.grid.at_grid["sea_level__elevation"]

    @sea_level.setter
    def sea_level(self, sea_level):
        self.grid.at_grid["sea_level__elevation"] = sea_level

    def calc_diffusion_coef_orig(self):
        """Calculate and store diffusion coefficient values.
        """
        sea_level = self.grid.at_grid["sea_level__elevation"]
        self._depth = sea_level - self._grid.at_node["topographic__elevation"]

        under_water = self._depth > 0.0
        deep_water = self._depth > self._wave_base
        land = ~under_water

        k = self.grid.at_node["kd"]

        k[under_water] = self._shallow_water_diffusivity

        k[deep_water] *= np.exp(
            -(self._depth[deep_water] - self._wave_base) / self._wave_base
        )

        k[land] = _TINY_DIFFUSIVITY

        return k

    def depth_function(self, water_depth):
        """
        Return weighting factor for transport.
        
        If there is no tidal range, then the weight factor is 1 if at or
        below sea level, and 0 if above it. If there is a tidal range, then
        a tanh function is used to weight transport across mean sea level, so
        that there is some degree of transport for water depths within the
        tidal range (less above, more below). The nature of the tanh function
        is such that the transport is about 95% of its maximum value at a depth
        of 1.5x the mean tidal range, and 5% of its maximum value at a height
        of 1.5x the mean tidal range above mean sea level.

        Parameters
        ----------
        water_depth : float array
            Depth of water relative to mean sea level (m) (can be negative)

        Returns
        -------
        df : float array
            Weight factor ranging from 0 to 1.
        """
        if self._tidal_range > 0.0:
            df = (np.tanh(self._inverse_tidal_range * water_depth) + 1.0) / 2.0
        else:
            df = 1.0 * (water_depth >= 0.0)
        return df

    def calc_diffusion_coef(self):
        """Calculate and store diffusion coefficient values.
        """
        sea_level = self.grid.at_grid["sea_level__elevation"]
        water_depth = sea_level - self._grid.at_node["topographic__elevation"]

        deep_water = water_depth > self._wave_base
        land = water_depth < 0.0

        k = self.grid.at_node["kd"]

        k[:] = self._shallow_water_diffusivity * self.depth_function(water_depth)

        k[deep_water] *= np.exp(
            -(water_depth[deep_water] - self._wave_base) / self._wave_base
        )

        k[land] += _TINY_DIFFUSIVITY

        return k

    # def shoreline_points(self, grid, z):
    #     sl_links = np.sign(z[grid.node_at_link_tail]) != np.sign(z[grid.node_at_link_head])
    #     slx = 0.5 * (grid.x_of_node[grid.node_at_link_tail[sl_links]] + grid.x_of_node[grid.node_at_link_head[sl_links]])
    #     sly = 0.5 * (grid.y_of_node[grid.node_at_link_tail[sl_links]] + grid.y_of_node[grid.node_at_link_head[sl_links]])
    #     return slx, sly

    # def distance_from_shoreline(self, grid, slx, sly, z):

    #     under_water = z <= 0.0
    #     uw = np.zeros((np.count_nonzero(under_water), 2))
    #     uw[:,0] = grid.x_of_node[under_water]
    #     uw[:,1] = grid.y_of_node[under_water]

    #     slxy = np.zeros((len(slx), 2))
    #     slxy[:,0] = slx
    #     slxy[:,1] = sly

    #     dist = cdist(uw, slxy)
    #     mindist = np.amin(dist, axis=1)

    #     dist_to_shore = np.zeros(grid.number_of_nodes)
    #     dist_to_shore[under_water] = mindist

    #     return dist_to_shore

    def run_one_step(self, dt):
        #z = self.grid.at_node['topographic__elevation']
        z_before = self.grid.at_node["topographic__elevation"].copy()

        # slx, sly = self.shoreline_points(self.grid, z)
        # d2s = self.distance_from_shoreline(self.grid, slx, sly, z)
        self.calc_diffusion_coef()

        # set elevation at upstream boundary to ensure proper sediment influx
        #x = self.grid.x_of_node.reshape(self.grid.shape)
        #z = self._grid.at_node["topographic__elevation"].reshape(self.grid.shape)
        # k = self._grid.at_node["kd"].reshape(self.grid.shape)
        # z[1, 0] = z[1,1] + self._load / k[1, 0] * (x[1,1]-x[1,0])
        #z[1, 0] = z[1, 1] + self._plain_slope * (x[1, 1] - x[1, 0])
        # self._load/self._load0)

        super(SimpleSubmarineDiffuser, self).run_one_step(dt)

        depo = self.grid.at_node["sediment_deposit__thickness"]
        depo[:] = (
            self.grid.at_node["topographic__elevation"] - z_before
        )

        self._time += dt
