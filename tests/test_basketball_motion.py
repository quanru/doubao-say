import math
import unittest

from doubao_input.ui.basketball_motion import basketball_pose


class BasketballMotionTest(unittest.TestCase):
    def pose(self, cycle):
        return basketball_pose(cycle * math.pi)

    def test_phrase_loops_without_a_pose_jump(self):
        self.assertEqual(self.pose(0), self.pose(1))
        start, end = self.pose(0), self.pose(1 - 1e-6)
        self.assertAlmostEqual(start.twist, end.twist, places=6)
        self.assertAlmostEqual(start.crouch, end.crouch, places=6)

    def test_shoulder_holds_and_head_follows_late(self):
        snap, hold = self.pose(0.52), self.pose(0.64)
        self.assertEqual(snap.twist, hold.twist)
        self.assertGreater(hold.head_turn, snap.head_turn)
        self.assertEqual(self.pose(0.62), self.pose(0.66))

    def test_hand_leads_ball_and_impact_squashes_at_floor(self):
        push, impact = self.pose(0.29), self.pose(0.34)
        self.assertLess(impact.hand_y, push.hand_y)
        self.assertGreater(impact.ball_y, push.ball_y)
        self.assertEqual(impact.squash, 1)
        self.assertAlmostEqual(impact.ball_y + 4.1 * (1 - .4 * impact.squash), 14.06)
        self.assertEqual(self.pose(0.6).squash, 0)

    def test_pose_stays_inside_canvas_across_cycle(self):
        for frame in range(300):
            pose = self.pose(frame / 300)
            self.assertLessEqual(pose.ball_y + 4.1 * (1 - .4 * pose.squash), 14.1)
            self.assertGreaterEqual(pose.ball_y - 4.1, -15.5)
