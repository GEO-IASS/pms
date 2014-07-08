#!/usr/bin/env python
import argparse
import json
import pickle

import numpy as np
from scipy.misc import imread
from scipy import sparse

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt


def getImage(filename):
    """Open image file in greyscale mode (intensity)."""
    return imread(filename, flatten=True)


def getLightning(filename):
    """Open JSON-formatted lightning file."""
    with open(filename, 'r') as fhdl:
        retVal = json.load(fhdl)
    return retVal


def photometricStereo(lightning_filename, images_filenames):
    """Based on Woodham '79 article.
    I = Matrix of input images, rows being different images.
    N = lightning vectors
    N_i = inverse of N
    rho = albedo of each pixels
    """
    lightning = getLightning(lightning_filename)
    images = list(map(getImage, images_filenames))
    n = len(images_filenames)

    I = np.vstack(x.ravel() for x in images)
    output = np.zeros((3, I.shape[1]))
    N = np.vstack(lightning[x] for x in images_filenames)
    N_i = np.linalg.pinv(N)
    rho = np.linalg.norm(N_i.dot( I ), axis=0)
    I = I / rho
    normals, residual, rank, s = np.linalg.lstsq(N, I[:, rho != 0].reshape(n, -1))
    output[:,rho != 0] = normals
    w, h = images[0].shape
    output = output.reshape(3, w, h).swapaxes(0, 2)
    # TODO: Raise an error on misbehavior of lstsq.

    return output

def photometricStereoWithoutLightning(images_filenames):
    """Based on Basri and al 2006 article."""
    images = list(map(getImage, images_filenames))
    f = len(images_filenames)
    n = images[0].size

    # Comments are taken directly from Basri and al, 2006
    # Begin with a set of images, each composing a row of the matrix M
    M = np.vstack(x.ravel() for x in images)

    # Using SVD M= U \delta V^T, factor M = \widetilde{L} \widetilde{S}, where
    # \widetilde{L} = U \sqrt{ \delta ^{f4} } and
    # \widetilde{S} = \sqrt{ \delta ^{4n} } V^T

    U, delta_vals, Vt = np.linalg.svd(M, full_matrices=False)
    Vt = sparse.dok_matrix(Vt)
    diag = Vt.diagonal()
    Vt.resize((max(M.shape), max(M.shape)))
    Vt.setdiag(np.hstack((
        diag,
        np.ones((1, max(M.shape) - diag.size)).ravel(),
    )))

    # Todo: to sparse
    delta = np.zeros((f, n))
    delta[:,:delta_vals.size] = np.diag(delta_vals)
    #L = U.dot( np.sqrt( delta[:,:4] ) )
    S = np.sqrt( delta[:4,:] ).dot ( Vt )

    # Normalise \widetilde{S} by scaling its rows so to have equal norms
    # NOTE: Apply the inverse to L, if the L matrix is ever neded
    S_norms = np.linalg.norm(S, axis=1)
    S[0,:] *= np.average(S_norms[1:]) / S_norms[0]

    # Construct Q. Each row of Q is constructed with quadratic terms cumputed
    # from a column of \widetilde{S}
    # [...] for a column \vec{q} in \widetilde{S} the corresponding row in Q is
    # (q_1^2, ... , q_4^2, 2 q_1 q_2, ... , 2 q_3 q_4)
    Q1 = np.take(S, (0, 1, 2, 3, 0, 0, 0, 1, 1, 2), axis=0)
    Q2 = np.take(S, (0, 1, 2, 3, 1, 2, 3, 2, 3, 3), axis=0)
    Q = Q1 * Q2
    Q[:,4:] *= 2
    Q = np.transpose(Q)

    # Using SVD, construct \widetilde{B} to approximate the null space of Q
    # (ie., solve Q \vec{b} = 0 and compose \widetilde{B} from the elements of
    # \vec{b}.
    UQ, SQ, VQ = np.linalg.svd(Q)
    b = VQ[:,9]
    B = np.take(b.flat, (0, 4, 5, 6,
                         4, 1, 7, 8,
                         5, 7, 2, 9,
                         6, 8, 9, 3)).reshape((4, 4))

    # Construct \widetilde{A}
    B_eig = np.linalg.eigvals(B)
    B_eig_sn = np.sign(B_eig)
    nb_eig_sn_positive = np.sum(B_eig_sn[B_eig_sn>0])
    nb_eig_sn_negative = np.sum(np.abs(B_eig_sn[B_eig_sn<0]))
    if 1 in (nb_eig_sn_positive, nb_eig_sn_negative):
        if nb_eig_sn_positive == 1:
            B = -B
        Lambda, W = np.linalg.eig(B)
        Lambda = np.abs(np.diag(Lambda))
        A = np.sqrt( Lambda ).dot( W )
    else:
        # Minimize the Frobenius norm
        UB, SB, VB = np.linalg.svd(B)
        A = UB.dot ( VB )
    import pdb; pdb.set_trace()

    # Compute the structure \widetilde{A} \widetilde{S}, which provides the
    # scene structure up to a scaled Lorentz transformation
    structure = A.dot( S )

    # Tests
    normals = structure[1:,:]
    normals /= np.linalg.norm(normals, axis=0)
    w, h = images[0].shape
    normals = normals.reshape(3, w, h).swapaxes(0, 2)
    return normals


def colorizeNormals(normals):
    """Generate an image representing the normals."""
    # Normalize the normals
    nf = np.linalg.norm(normals, axis=normals.ndim - 1)
    normals_n = normals / np.dstack((nf, nf, nf))

    color = (normals_n + 1) / 2

    return color

def generateNormalMap(dims=600):
    """Generate a mapping of the normals of a perfect sphere."""
    x, y = np.meshgrid(np.linspace(-1, 1, dims), np.linspace(-1, 1, dims))
    zsq = 1 - np.power(x, 2) - np.power(y, 2)

    valid = zsq >= 0

    z = np.zeros(x.shape)
    z[valid] = np.sqrt(zsq[valid])

    this_array = np.dstack([x, -y, z]).swapaxes(0, 1)
    color = colorizeNormals(this_array)
    img = color

    img[~valid] = 0

    return img


def main():
    parser = argparse.ArgumentParser(
        description="Photometric Stereo",
    )
    parser.add_argument(
        "lightning",
        nargs="?",
        help="Filename of JSON file containing lightning information",
    )
    parser.add_argument(
        "image",
        nargs="*",
        help="Images filenames",
    )
    parser.add_argument(
        "--generate-map",
        action='store_true',
        help="Generate a map.png file which represends the colors of the "
             "normal mapping.",
    )
    args = parser.parse_args()
        
    if args.generate_map:
        normals = generateNormalMap()
        plt.imsave('map.png', normals)
        return

    if not (args.lightning and len(args.image) >= 3):
        print("Please specify a lightning file and 3+ image files.")
        return

    try:
        with open('data.pkl', 'rb') as fhdl:
            normals = pickle.load(fhdl)
    except:
        normals = photometricStereo(args.lightning, args.image)
        with open('data.pkl', 'wb') as fhdl:
            pickle.dump(normals, fhdl)

    color = colorizeNormals(normals)
    plt.imsave('out.png', color)


if __name__ == "__main__":
    main()