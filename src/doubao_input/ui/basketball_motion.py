"""A timed dribble phrase; speech cadence controls playback, not body scale."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BasketballPose:
    crouch: float
    twist: float
    head_turn: float
    hand_y: float
    ball_y: float
    squash: float


# time, crouch, shoulder twist, delayed head turn, hand Y, ball Y, ball squash
# Anticipation → push → impact → shoulder snap → hold → release.
KEYFRAMES = (
    (0.00, 0.10, 0.00, 0.00, -7.0, -3.0, 0.00),
    (0.16, 1.00, -0.25, -0.10, -6.0, -3.0, 0.00),
    (0.29, 0.75, 0.15, -0.15, 3.0, 5.0, 0.00),
    (0.34, 0.65, 0.40, -0.15, 1.0, 11.6, 1.00),
    (0.40, 0.45, 0.65, -0.10, -1.0, 8.0, 0.00),
    (0.52, 0.15, 1.00, 0.10, -5.0, -1.0, 0.00),
    (0.60, 0.15, 1.00, 0.55, -7.0, -3.0, 0.00),
    (0.68, 0.15, 1.00, 0.55, -7.0, -3.0, 0.00),
    (0.84, 0.30, 0.10, 0.35, -7.0, -3.0, 0.00),
    (1.00, 0.10, 0.00, 0.00, -7.0, -3.0, 0.00),
)


def basketball_pose(phase):
    cycle = (phase / math.pi) % 1
    for left, right in zip(KEYFRAMES, KEYFRAMES[1:]):
        if cycle <= right[0]:
            t = (cycle - left[0]) / (right[0] - left[0])
            ease = t * t * (3 - 2 * t)
            return BasketballPose(*(a + (b - a) * ease for a, b in zip(left[1:], right[1:])))
    return BasketballPose(*KEYFRAMES[-1][1:])
