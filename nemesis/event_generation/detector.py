"""Collection of classes implementing a detector."""
import itertools

import awkward as ak
import numpy as np
import scipy.stats

class Module(object):
    """
    Detection module.

    Attributes:
        pos: np.ndarray
            Module position (x, y, z)
        noise_rate: float
            Noise rate in 1/ns
        efficiency: float
            Module efficiency (0, 1]
        self.key: collection
            Module identifier
    """

    def __init__(self, pos, key, noise_rate=1, efficiency=0.2):
        """Initialize a module."""
        self.pos = pos
        self.noise_rate = noise_rate
        self.efficiency = efficiency
        self.key = key

    def __repr__(self):
        """Return string representation."""
        return repr(
            f"Module {self.key}, {self.pos} [m], {self.noise_rate} [Hz], {self.efficiency}"
        )
        
class Detector(object):
    """
    A collection of modules.

    Attributes:
        modules: List
        module_coords: np.ndarray
            N x 3 array of (x, y z) coordinates
        module_coords_ak: ak.array
            Awkward array representation of the module coordinates
        module_efficiencies: np.ndarray
            N array of the module efficiences
    """

    def __init__(self, modules):
        """Initialize detector."""
        self.modules = modules
        self.module_coords = np.vstack([m.pos for m in self.modules])
        self.module_coords_ak = ak.Array(self.module_coords)
        self.module_efficiencies = np.asarray([m.efficiency for m in self.modules])
        self.module_noise_rates = np.asarray([m.noise_rate for m in self.modules])
        
        self._outer_radius = np.linalg.norm(self.module_coords, axis=1).max()
        self._outer_cylinder = (
            np.linalg.norm(self.module_coords[:, :2], axis=1).max(),
            2 * np.abs(self.module_coords[:, 2].max()),
        )
        self._n_modules = len(modules)

    @property
    def n_modules(self):
        return self._n_modules

    @property
    def outer_radius(self):
        return self._outer_radius

    @property
    def outer_cylinder(self):
        return self._outer_cylinder
    
def make_line(x, y, n_z, dist_z, rng, baseline_noise_rate, line_id, efficiency=0.2):
    """
    Make a line of detector modules.

    The modules share the same (x, y) coordinate and are spaced along the z-direction.

    Parameters:
        x, y: float
            (x, y) position of the line
        n_z: int
            Number of modules per line
        dist_z: float
            Spacing of the detector modules in z
        rng: RandomState
        baseline_noise_rate: float
            Baseline noise rate in 1/ns. Will be multiplied to gamma(1, 0.25) distributed
            random rates per module.
        line_id: int
            Identifier for this line
    """
    modules = []
    for i, pos_z in enumerate(np.linspace(-dist_z * n_z / 2, dist_z * n_z / 2, n_z)):
        pos = np.array([x, y, pos_z])
        noise_rate = (
            scipy.stats.gamma.rvs(1, 0.25, random_state=rng) * baseline_noise_rate
        )
        mod = Module(
            pos, key=(line_id, i), noise_rate=noise_rate, efficiency=efficiency
        )
        modules.append(mod)
    return modules


def make_triang(
    side_len,
    oms_per_line=20,
    dist_z=50,
    dark_noise_rate=16 * 1e-5,
    rng=np.random.RandomState(0),
    efficiency=0.5,
):

    height = np.sqrt(side_len**2 - (side_len / 2) ** 2)

    modules = make_line(
        -side_len / 2,
        -height / 3,
        oms_per_line,
        dist_z,
        rng,
        dark_noise_rate,
        0,
        efficiency=efficiency,
    )
    modules += make_line(
        side_len / 2,
        -height / 3,
        oms_per_line,
        dist_z,
        rng,
        dark_noise_rate,
        1,
        efficiency=efficiency,
    )
    modules += make_line(
        0,
        2 / 3 * height,
        oms_per_line,
        dist_z,
        rng,
        dark_noise_rate,
        2,
        efficiency=efficiency,
    )

    det = Detector(modules)

    return det


def sample_cylinder_surface(height, radius, n, rng=np.random.RandomState(1337)):
    """Sample points on a cylinder surface."""
    side_area = 2 * np.pi * radius * height
    top_area = 2 * np.pi * radius ** 2

    ratio = top_area / (top_area + side_area)

    is_top = rng.uniform(0, 1, size=n) < ratio
    n_is_top = is_top.sum()
    samples = np.empty((n, 3))
    theta = rng.uniform(0, 2 * np.pi, size=n)

    # top / bottom points

    r = radius * np.sqrt(rng.uniform(0, 1, size=n_is_top))

    samples[is_top, 0] = r * np.sin(theta[is_top])
    samples[is_top, 1] = r * np.cos(theta[is_top])
    samples[is_top, 2] = rng.choice(
        [-height / 2, height / 2], replace=True, size=n_is_top
    )

    # side points

    r = radius
    samples[~is_top, 0] = r * np.sin(theta[~is_top])
    samples[~is_top, 1] = r * np.cos(theta[~is_top])
    samples[~is_top, 2] = rng.uniform(-height / 2, height / 2, size=n - n_is_top)

    return samples

def sample_cylinder_volume(height, radius, n, rng=np.random.RandomState(1337)):
    """Sample points in cylinder volume."""
    theta = rng.uniform(0, 2 * np.pi, size=n)
    r = radius * np.sqrt(rng.uniform(0, 1, size=n))
    samples = np.empty((n, 3))
    samples[:, 0] = r * np.sin(theta)
    samples[:, 1] = r * np.cos(theta)
    samples[:, 2] = rng.uniform(-height / 2, height / 2, size=n)
    return samples


def sample_direction(n_samples, rng=np.random.RandomState(1337)):
    """Sample uniform directions."""
    cos_theta = rng.uniform(-1, 1, size=n_samples)
    theta = np.arccos(cos_theta)
    phi = rng.uniform(0, 2 * np.pi)

    samples = np.empty((n_samples, 3))
    samples[:, 0] = np.sin(theta) * np.cos(phi)
    samples[:, 1] = np.sin(theta) * np.sin(phi)
    samples[:, 2] = np.cos(theta)

    return samples

def generate_noise(det, time_range, rng=np.random.RandomState(1337)):
    """Generate detector noise in a time range."""
    all_times_det = []
    dT = np.diff(time_range)
    for idom in range(len(det.modules)):
        noise_amp = rng.poisson(det.modules[idom].noise_rate * dT)
        times_det = rng.uniform(*time_range, size=noise_amp)
        all_times_det.append(times_det)

    return ak.sort(ak.Array(all_times_det))

def trigger(det, event_times, mod_thresh=8, phot_thres=5):
    """
    Check a simple multiplicity condition.

    Trigger is true when at least `mod_thresh` modules have measured more than `phot_thres` photons.

    Parameters:
        det: Detector
        event_times: ak.array
        mod_thresh: int
            Threshold for the number of modules which have detected `phot_thres` photons
        phot_thres: int
            Threshold for the number of photons per module
    """
    hits_per_module = ak.count(event_times, axis=1)
    if ak.sum((hits_per_module > phot_thres)) > mod_thresh:
        return True
    return False

