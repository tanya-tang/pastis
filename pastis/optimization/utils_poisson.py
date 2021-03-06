from __future__ import print_function

import numpy as np
import sys


if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")


def _print_code_header(header, sub_header=None, max_length=80,
                       blank_lines=None,
                       verbose=True):
    """Prints a header, for demarcation of output.
    """

    if verbose:
        print('=' * max_length, flush=True)
        print(('=' * int(np.ceil((max_length - len(header) - 2) / 2))) + ' %s ' %
              header + ('=' * int(np.floor((max_length - len(header) - 2) / 2))), flush=True)
        if sub_header is not None and len(sub_header) != 0:
            print(('=' * int(np.ceil((max_length - len(sub_header) - 2) / 2))) + ' %s ' %
                  sub_header + ('=' * int(np.floor((max_length - len(sub_header) - 2) / 2))), flush=True)
        print('=' * max_length, flush=True)
        if blank_lines is not None and blank_lines > 0:
            print('\n' * (blank_lines - 1), flush=True)


def _format_structures(structures, lengths, ploidy, mixture_coefs=None):
    """Reformats and checks shape of structures.
    """

    from .poisson import _format_X

    if isinstance(structures, list):
        if not all([isinstance(struct, np.ndarray) for struct in structures]):
            raise ValueError("Individual structures must use numpy.ndarray"
                             "format.")
        try:
            structures = [struct.reshape(-1, 3) for struct in structures]
        except ValueError:
            raise ValueError("Structures should be composed of 3D coordinates")
    else:
        if not isinstance(structures, np.ndarray):
            raise ValueError("Structures must be numpy.ndarray or list of"
                             "numpy.ndarrays.")
        try:
            structures = structures.reshape(-1, 3)
        except ValueError:
            raise ValueError("Structure should be composed of 3D coordinates")
        structures, _ = _format_X(structures, mixture_coefs=mixture_coefs)

    if mixture_coefs is not None and len(structures) != len(mixture_coefs):
        raise ValueError("The number of structures (%d) and of mixture "
                         "coefficents (%d) should be identical." %
                         (len(structures), len(mixture_coefs)))

    if len(set([struct.shape[0] for struct in structures])) > 1:
        raise ValueError("Structures are of different shapes.")

    nbeads = lengths.sum() * ploidy
    for struct in structures:
        if struct.shape[0] != nbeads:
            raise ValueError("Structure is of unexpected shape. Expected %d"
                             "beads, structure is %d by 3."
                             % (nbeads, struct.shape[0]))

    return structures


def find_beads_to_remove(counts, nbeads, threshold=0):
    """Determine beads for which no corresponding counts data exists.

    Identifies beads that should be removed (set to NaN) in the structure.
    If there aren't any counts in the rows/columns corresponding to a given
    bead, that bead should be removed.

    Parameters
    ----------
    counts : list of np.ndarray or scipy.sparse.coo_matrix
        Counts data.
    nbeads : int
        Total number of beads in the structure.

    Returns
    -------
    torm : array of bool of shape (nbeads,)
        Beads that should be removed (set to NaN) in the structure.
    """

    if not isinstance(counts, list):
        counts = [counts]
    inverse_torm = np.zeros(int(nbeads))
    for c in counts:
        if isinstance(c, np.ndarray):
            axis0sum = np.tile(
                np.array(np.nansum(c, axis=0).flatten()).flatten(),
                int(nbeads / c.shape[1]))
            axis1sum = np.tile(
                np.array(np.nansum(c, axis=1).flatten()).flatten(),
                int(nbeads / c.shape[0]))
        else:
            axis0sum = np.tile(
                np.array(c.sum(axis=0).flatten()).flatten(),
                int(nbeads / c.shape[1]))
            axis1sum = np.tile(
                np.array(c.sum(axis=1).flatten()).flatten(),
                int(nbeads / c.shape[0]))
        inverse_torm += (axis0sum + axis1sum > threshold).astype(int)
    torm = ~ inverse_torm.astype(bool)
    return torm


def _struct_replace_nan(struct, lengths, kind='linear', random_state=None):
    """Replace NaNs in structure via linear interpolation.
    """

    from scipy.interpolate import interp1d
    from warnings import warn
    from sklearn.utils import check_random_state

    if random_state is None:
        random_state = np.random.RandomState(seed=0)
    random_state = check_random_state(random_state)

    if isinstance(struct, str):
        struct = np.loadtxt(struct)
    else:
        struct = struct.copy()
    struct = struct.reshape(-1, 3)
    lengths = np.array(lengths).astype(int)

    ploidy = 1
    if len(struct) > lengths.sum():
        ploidy = 2

    if not np.isnan(struct).any():
        return(struct)
    else:
        nan_chroms = []
        mask = np.invert(np.isnan(struct[:, 0]))
        interpolated_struct = np.zeros(struct.shape)
        begin, end = 0, 0
        for j, length in enumerate(np.tile(lengths, ploidy)):
            end += length
            to_rm = mask[begin:end]
            if to_rm.sum() <= 1:
                interpolated_chr = (
                    1 - 2 * random_state.rand(length * 3)).reshape(-1, 3)
                if ploidy == 1:
                    nan_chroms.append(str(j + 1))
                else:
                    nan_chroms.append(
                        str(j + 1) + '_homo1' if j < lengths.shape[0] else str(j / 2 + 1) + '_homo2')
            else:
                m = np.arange(length)[to_rm]
                beads2interpolate = np.arange(m.min(), m.max() + 1, 1)

                interpolated_chr = np.full_like(struct[begin:end, :], np.nan)
                interpolated_chr[beads2interpolate, 0] = interp1d(
                    m, struct[begin:end, 0][to_rm], kind=kind)(beads2interpolate)
                interpolated_chr[beads2interpolate, 1] = interp1d(
                    m, struct[begin:end, 1][to_rm], kind=kind)(beads2interpolate)
                interpolated_chr[beads2interpolate, 2] = interp1d(
                    m, struct[begin:end, 2][to_rm], kind=kind)(beads2interpolate)

                # Fill in beads at start
                diff_beads_at_chr_start = interpolated_chr[beads2interpolate[
                    1], :] - interpolated_chr[beads2interpolate[0], :]
                how_far = 1
                for j in reversed(range(min(beads2interpolate))):
                    interpolated_chr[j, :] = interpolated_chr[
                        beads2interpolate[0], :] - diff_beads_at_chr_start * how_far
                    how_far += 1
                # Fill in beads at end
                diff_beads_at_chr_end = interpolated_chr[
                    beads2interpolate[-2], :] - interpolated_chr[beads2interpolate[-1], :]
                how_far = 1
                for j in range(max(beads2interpolate) + 1, length):
                    interpolated_chr[j, :] = interpolated_chr[
                        beads2interpolate[-1], :] - diff_beads_at_chr_end * how_far
                    how_far += 1

            interpolated_struct[begin:end, :] = interpolated_chr
            begin = end

        if len(nan_chroms) != 0:
            warn('The following chromosomes were all NaN: ' + ' '.join(nan_chroms))

        return(interpolated_struct)
