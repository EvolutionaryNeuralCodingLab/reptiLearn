"""
This module is responsible for correcting the distortion of the camera lens using existing functions from Open-CV.
As the camera is located close to the target, and captures a relatively wide angle frame, the barrel distortion is
significant. The function get_distortion_matrix analyzes images that contain a checkerboard, and produces the
required undistortion matrix and coefficients. These values are constant for a specific camera and lens combination.
The function get_undistort_mapping computes from these parameters the required transformations, to be used with images,
single points of data, or data arrays.
"""

import numpy as np
import cv2 as cv
from pathlib import Path

# Undistortion code from:
#   https://opencv-python-tutroals.readthedocs.io/en/latest/py_tutorials/py_calib3d/py_calibration/py_calibration.html

# Static un-distortion matrices for the cameras.

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

ARUCO_DICTIONARIES = {
    "4X4_50": cv.aruco.DICT_4X4_50,
    "4X4_100": cv.aruco.DICT_4X4_100,
    "4X4_250": cv.aruco.DICT_4X4_250,
    "4X4_1000": cv.aruco.DICT_4X4_1000,
    "5X5_50": cv.aruco.DICT_5X5_50,
    "5X5_100": cv.aruco.DICT_5X5_100,
    "5X5_250": cv.aruco.DICT_5X5_250,
    "5X5_1000": cv.aruco.DICT_5X5_1000,
    "6X6_50": cv.aruco.DICT_6X6_50,
    "6X6_100": cv.aruco.DICT_6X6_100,
    "6X6_250": cv.aruco.DICT_6X6_250,
    "6X6_1000": cv.aruco.DICT_6X6_1000,
    "7X7_50": cv.aruco.DICT_7X7_50,
    "7X7_100": cv.aruco.DICT_7X7_100,
    "7X7_250": cv.aruco.DICT_7X7_250,
    "7X7_1000": cv.aruco.DICT_7X7_1000,
}


class CalibrationException(Exception):
    pass


def _iter_image_paths(image_dir: Path):
    return sorted(
        p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def get_aruco_dictionary(name: str):
    key = name.upper().replace("DICT_", "")
    if key not in ARUCO_DICTIONARIES:
        known = ", ".join(sorted(ARUCO_DICTIONARIES))
        raise CalibrationException(f"Unknown ArUco dictionary {name!r}. Known: {known}")
    return cv.aruco.getPredefinedDictionary(ARUCO_DICTIONARIES[key])


def make_charuco_board(
    squares_x: int,
    squares_y: int,
    *,
    square_length: float = 1.0,
    marker_length: float = 0.75,
    dictionary: str = "4X4_250",
    legacy_pattern: bool = False,
):
    board = cv.aruco.CharucoBoard(
        (squares_x, squares_y),
        squareLength=square_length,
        markerLength=marker_length,
        dictionary=get_aruco_dictionary(dictionary),
    )
    board.setLegacyPattern(legacy_pattern)
    return board


def get_distortion_matrix_charuco(
    image_dir: Path,
    squares_x: int,
    squares_y: int,
    *,
    square_length: float = 1.0,
    marker_length: float = 0.75,
    dictionary: str = "4X4_250",
    legacy_pattern: bool = False,
    min_corners: int = 12,
):
    """
    Finds the undistortion matrix from multiple images of a ChArUco board.

    Uses CharucoDetector + board.matchImagePoints, then cv.calibrateCamera.
    Physical square/marker sizes only need to be consistent across images, not
    accurate in millimeters.

    :param image_dir: folder with calibration images
    :param squares_x: number of chessboard squares along X (OpenCV CharucoBoard width)
    :param squares_y: number of chessboard squares along Y
    :param square_length: relative square size (default 1.0)
    :param marker_length: relative marker size (default 0.75)
    :param dictionary: ArUco dictionary name, e.g. "4X4_250"
    :param legacy_pattern: True for older ChArUco boards (pre-OpenCV 4.6 layout)
    :param min_corners: minimum detected ChArUco corners required per image
    :return: dict with "mtx", "dist", "n_images", "reprojection_error"
    """
    from tqdm.auto import tqdm

    board = make_charuco_board(
        squares_x,
        squares_y,
        square_length=square_length,
        marker_length=marker_length,
        dictionary=dictionary,
        legacy_pattern=legacy_pattern,
    )
    detector = cv.aruco.CharucoDetector(board)

    objpoints = []
    imgpoints = []
    image_size = None
    image_paths = _iter_image_paths(image_dir)

    if not image_paths:
        raise CalibrationException(f"No images found in {image_dir}")

    for fname in tqdm(image_paths):
        img = cv.imread(str(fname))
        if img is None:
            raise CalibrationException(f"Can't read image at {fname}")

        gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
        image_size = (gray.shape[1], gray.shape[0])

        charuco_corners, charuco_ids, _, _ = detector.detectBoard(gray)
        if charuco_corners is None or charuco_ids is None:
            continue
        if len(charuco_corners) < min_corners:
            continue

        obj_points, img_points = board.matchImagePoints(charuco_corners, charuco_ids)
        if obj_points is None or len(obj_points) < min_corners:
            continue

        objpoints.append(obj_points)
        imgpoints.append(img_points)

    if not objpoints:
        raise CalibrationException(
            f"No usable ChArUco detections in {image_dir}. "
            f"Check squares_x/y, dictionary, and legacy_pattern."
        )

    ret, mtx, dist, _rvecs, _tvecs = cv.calibrateCamera(
        objpoints, imgpoints, image_size, None, None
    )

    if not ret:
        raise CalibrationException("Error finding distortion matrix from ChArUco board")

    return {
        "mtx": mtx,
        "dist": dist,
        "n_images": len(objpoints),
        "reprojection_error": float(ret),
    }


def get_distortion_matrix(chkr_im_path: Path, rows=6, cols=9, *, verbose=True):
    """
    Finds the undistortion matrix of the lens based on multiple images
    with a plain checkerboard (not ChArUco). For ChArUco boards, use
    get_distortion_matrix_charuco() instead.

    :param: chkr_im_path - path to folder with images with checkerboards
    :param: rows - number of inner corner rows in checkerboard
    :param: cols - number of inner corner cols in checkerboard
    :param: verbose - when True, print detection result for every image
    :return: dict with "mtx", "dist", "n_images", "reprojection_error"
    """
    from tqdm.auto import tqdm

    sb_flags = cv.CALIB_CB_EXHAUSTIVE + cv.CALIB_CB_ACCURACY

    # prepare object points, like (0,0,0), (1,0,0), (2,0,0) ....,(6,5,0)
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)

    # Arrays to store object points and image points from all the images.
    objpoints = []  # 3d point in real world space
    imgpoints = []  # 2d points in image plane.

    image_paths = _iter_image_paths(chkr_im_path)
    if not image_paths:
        raise CalibrationException(f"No images found in {chkr_im_path}")

    for fname in tqdm(image_paths, disable=not verbose):
        img = cv.imread(str(fname))
        if img is None:
            raise CalibrationException(f"Can't read image at {fname}")
        shape = img.shape
        gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)

        ret, corners = cv.findChessboardCornersSB(gray, (cols, rows), sb_flags)
        if verbose:
            print(fname.name, ret, flush=True)

        if ret:
            objpoints.append(objp)
            imgpoints.append(corners)

    if verbose:
        print(
            f"Checkerboard detected in {len(objpoints)}/{len(image_paths)} images",
            flush=True,
        )

    if not objpoints:
        raise CalibrationException(
            f"No checkerboard detections in {chkr_im_path}. Check rows/cols."
        )

    ret, mtx, dist, rvecs, tvecs = cv.calibrateCamera(
        objpoints, imgpoints, shape[::-1][1:], None, None
    )

    if not ret:
        raise CalibrationException("Error finding distortion matrix")

    return {
        "mtx": mtx,
        "dist": dist,
        "n_images": len(objpoints),
        "reprojection_error": float(ret),
    }


def normalize_cam_attr(cam_attr):
    """
    Convert mtx/dist from config.py list literals to numpy arrays for OpenCV.
    """
    return {
        "mtx": np.asarray(cam_attr["mtx"], dtype=np.float64),
        "dist": np.asarray(cam_attr["dist"], dtype=np.float64),
    }


def get_undistort_mapping(width, height, cam_attr, alpha=0):
    """
    Computes the undistortion mapping for the given mtx and dist matrices.

    :param width: int, width of the image
    :param height: int, height of the image
    :param cam_attr: A dictionary with "mtx" and "dist" keys for a specific camera and lens.
    :param dist: numpy array, distortion coefficients
    :param alpha: float in the range (0,1)
    :return:
        mapx, mapy - numpy arrays, x,y coordinates for each image coordinate for undistorting an image.
        roi - tuple, (x, y, w, h) region of interest tuple
        newcameramtx - numpy array,  camera matrix for undistorting points in the specific (width, height) frame.
    """
    cam_attr = normalize_cam_attr(cam_attr)
    newcameramtx, roi = cv.getOptimalNewCameraMatrix(
        cam_attr["mtx"], cam_attr["dist"], (width, height), alpha, (width, height)
    )
    return (
        cv.initUndistortRectifyMap(
            cam_attr["mtx"], cam_attr["dist"], None, newcameramtx, (width, height), 5
        ),
        roi,
        newcameramtx,
    )


def undistort_image(img, mapping, roi=None):
    """
    When roi is not None the image is cropped to the ROI.
    :param img: numpy array: image to undistort
    :param mapping: a tuple (mapx, mapy)
    :return: numpy array: undistorted version of img according to the mapping
    """
    mapx, mapy = mapping

    dst = cv.remap(img, mapx, mapy, cv.INTER_LINEAR)

    # crop the image
    if roi:
        x, y, w, h = roi
        dst = dst[y : y + h, x : x + w]

    return dst


def undistort_point(p, newcameramtx, cam_attr):
    """
    :param p: iterable, coordinate to undistort
    :param newcameramtx: numpy array, camera matrix for the specific (width, height) frame.
    :param cam_attr: A dictionary with "mtx" and "dist" keys for a specific camera and lens.
    :return: numpy array, undistorted points
    """

    p = np.array(p)
    if np.any(np.isnan(p)):
        return np.nan, np.nan

    cam_attr = normalize_cam_attr(cam_attr)
    return cv.undistortPoints(
        np.expand_dims(p, axis=0), newcameramtx, cam_attr["dist"]
    ).squeeze()


def undistort_data(
    data, width, height, cam_attr, cols=(("x1", "y1"), ("x2", "y2")), alpha=0
):
    """
    Undistorts a bulk of data. assumes location data in (cent_x, cent_y, x1, y1, x2, y2) format
    :param data: Pandas DataFrame, data to undistort
    :param width: int
    :param height: int
    :param cols: tuple of pairs of strings which are column names in the df
    :param cam_attr: A dictionary with "mtx" and "dist" keys for a specific camera and lens.
    :param alpha: float in (0,1)
    :return: pandas df, the undistorted data (deep copy of the original data)
    """

    # deep copy of the original data
    ret_df = data.copy()

    # get transformation for the specific frame
    _, _, newcameramtx = get_undistort_mapping(width, height, cam_attr, alpha=alpha)

    # for each pair of columns which constitute a coordinate, undistort
    for xy in cols:
        x = xy[0]
        y = xy[1]
        points = data[[x, y]].values
        undistorted = cv.undistortPoints(
            np.expand_dims(points, axis=0),
            newcameramtx,
            cam_attr["dist"],
            P=newcameramtx,
        )
        ret_df[[x, y]] = undistorted.squeeze(1)

    return ret_df
