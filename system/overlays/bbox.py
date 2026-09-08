import cv2
import numpy as np

from overlay import ObserverOverlay, is_point_in_bounds


class BBoxOverlay(ObserverOverlay):
    default_params = {
        **ObserverOverlay.default_params,
        "show_centroid": True,
        "show_bbox": True,
        "centroid_color": (255, 0, 0),
        "centroid_dot_radius": 4,
        "bbox_color": (0, 0, 128),
        "bbox_line_thickness": 2,
    }

    def obs_apply(self, img, img_timestamp, obs_out, obs_out_timestamp):
        # Observer output stores normalized coords in [0,1].
        h, w = img.shape[:2]

        # Snapshot the shared observer buffer so a concurrent write cannot
        # change values between validation and int() conversion.
        obs = np.asarray(obs_out, dtype=np.float64).copy()
        if obs.size < 5:
            return img

        bbox = obs[:4]
        if not np.all(np.isfinite(bbox)):
            return img

        # Promote single-channel (grayscale) frames to BGR so the colored
        # bbox/keypoint defaults render correctly. On a 1-channel image
        # OpenCV would otherwise collapse a BGR tuple to its first scalar
        # (e.g. (0,255,0) -> intensity 0 -> a near-invisible black box).
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.ndim == 3 and img.shape[2] == 1:
            img = cv2.cvtColor(img.squeeze(-1), cv2.COLOR_GRAY2BGR)

        x1, y1, x2, y2 = bbox
        x1, x2 = int(x1 * w), int(x2 * w)
        y1, y2 = int(y1 * h), int(y2 * h)

        if self.get_config("show_bbox"):
            cv2.rectangle(
                img,
                (x1, y1),
                (x2, y2),
                self.get_config("bbox_color"),
                self.get_config("bbox_line_thickness"),
            )
            conf = obs[4]
            if np.isfinite(conf):
                conf = float(conf)
                label = f"turtle {conf:.2f}"
                text_y = y1 - 8 if y1 > 12 else y1 + 14
                cv2.putText(
                    img,
                    label,
                    (x1, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    self.get_config("bbox_color"),
                    1,
                    cv2.LINE_AA,
                )

        if self.get_config("show_centroid"):
            c = ((x1 + x2) // 2, (y1 + y2) // 2)
            if is_point_in_bounds(c, img):
                cv2.circle(
                    img,
                    center=tuple(c),
                    radius=self.get_config("centroid_dot_radius"),
                    color=self.get_config("centroid_color"),
                    thickness=-1,
                    lineType=cv2.LINE_AA,
                )

        # Optional keypoints start at index 5: [k1x, k1y, k2x, k2y, ...] normalized.
        if obs.size > 5:
            for i in range(5, obs.size - 1, 2):
                kx, ky = obs[i], obs[i + 1]
                if not (np.isfinite(kx) and np.isfinite(ky)):
                    continue
                px, py = int(kx * w), int(ky * h)
                if is_point_in_bounds((px, py), img):
                    cv2.circle(
                        img,
                        center=(px, py),
                        radius=3,
                        color=(0, 255, 255),
                        thickness=-1,
                        lineType=cv2.LINE_AA,
                    )

        return img
