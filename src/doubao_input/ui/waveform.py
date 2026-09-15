"""Cairo listening styles, usable without a GTK display or microphone."""
import math

import cairo


def draw_waveform(cr, style, motion, width, height, accent, foreground, *, reduced_motion=False):
    cr.save()
    cr.rectangle(0, 0, width, height)
    cr.clip()
    # Reduced motion keeps audio feedback but removes travelling/bouncing motion.
    phase = 0.0 if reduced_motion or motion.level < 0.001 else motion.phase
    if style == "waves":
        draw_waves(cr, motion.level, phase, width, height, accent)
    elif style == "ripples":
        draw_ripples(cr, motion.level, phase, width / 2, height / 2,
                     width * 0.44, height * 0.43, accent)
    elif style == "basketball":
        draw_basketball(cr, motion.level, phase, width, height, accent, foreground)
    else:
        draw_bars(cr, motion, width, accent, foreground)
    cr.restore()


def draw_bars(cr, motion, width, accent, foreground):
    samples = motion.bars(48)
    gradient = cairo.LinearGradient(0, 0, 0, 24)
    gradient.add_color_stop_rgba(0, *accent, 0.55)
    gradient.add_color_stop_rgba(0.5, *foreground, 0.95)
    gradient.add_color_stop_rgba(1, *accent, 0.55)
    wave_width = 48 * (4 + 3)
    start_x = (width - wave_width + 3) / 2
    centre_y = 24 / 2
    for index, sample in enumerate(samples):
        amplitude = 0.85 + sample * (24 / 2 - 2)
        x = start_x + index * (4 + 3)
        # A restrained halo follows actual energy, never idle breathing.
        cr.set_source_rgba(*accent, motion.level * 0.18)
        rounded_rect(cr, x - 1.5, centre_y - amplitude - 1.5,
                      4 + 3, amplitude * 2 + 3, 3)
        cr.fill()
        cr.set_source(gradient)
        rounded_rect(
            cr,
            x,
            centre_y - amplitude,
            4,
            amplitude * 2,
            4 / 2,
        )
        cr.fill()


def rounded_rect(
    cr, x: float, y: float, width: float, height: float, radius: float
) -> None:
    if width <= 0 or height <= 0:
        return
    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_waves(cr, level, phase, width, height, accent):
    for layer in range(3):
        cr.set_source_rgba(*accent, 0.85 - layer * 0.24)
        cr.set_line_width(1.6 - layer * 0.25)
        for i in range(121):
            x = i / 120
            envelope = math.sin(math.pi * x) ** 1.2
            y = height / 2 + level * (height / 2 - 3) * envelope * math.sin(
                x * math.tau * 2 + phase + layer * 0.8)
            if i == 0:
                cr.move_to(12 + x * (width - 24), y)
            else:
                cr.line_to(12 + x * (width - 24), y)
        cr.stroke()


def draw_ripples(cr, level, phase, x, y, rx, ry, color):
    for ring in range(4):
        progress = (phase / math.tau + ring / 4) % 1
        scale = 0.12 + 0.88 * progress
        cr.save()
        cr.translate(x, y)
        cr.scale(rx, ry)
        cr.set_source_rgba(*color, (0.12 + level * 0.75) * (1 - progress))
        cr.set_line_width(0.07)
        cr.arc(0, 0, scale, 0, math.tau)
        cr.stroke()
        cr.restore()


def draw_basketball(cr, level, phase, width, height, accent, foreground):
    # Original tiny cartoon: centre-parted hair, dark shirt, light suspenders.
    bounce = abs(math.sin(phase)) * level
    sway = math.sin(phase) * level * 2
    cx = width / 2 - 13
    ball_x, ball_y = cx + 26, 25 - 12 * bounce
    draw_ripples(cr, level, phase, ball_x, 28, width * 0.38, 2.3, accent)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)

    def line(points, color, thickness):
        cr.set_source_rgb(*color)
        cr.set_line_width(thickness)
        cr.move_to(*points[0])
        for point in points[1:]:
            cr.line_to(*point)
        cr.stroke()

    skin = (0.98, 0.79, 0.63)
    dark = (0.16, 0.17, 0.23)
    # Bent knees and a reaching dribble hand.
    line([(cx - 3, 19), (cx - 6 - sway, 23), (cx - 3 - sway, 28)], foreground, 2.8)
    line([(cx + 3, 19), (cx + 7 + sway, 23), (cx + 10 + sway, 28)], foreground, 2.8)
    line([(cx - 4 + sway, 12), (cx - 10, 16), (cx - 7, 19)], skin, 2)
    line([(cx + 4 + sway, 12), (cx + 13, 13), (ball_x - 1, ball_y - 5)], skin, 2)
    line([(cx + sway, 11), (cx, 19)], dark, 8)
    for offset in (-2.4, 2.4):
        line([(cx + sway + offset, 11), (cx + offset, 19)], foreground, 1.3)
    cr.set_source_rgb(*skin)
    cr.arc(cx + sway, 6, 3.8, 0, math.tau)
    cr.fill()
    for direction in (-1, 1):
        cr.set_source_rgb(*foreground)
        cr.move_to(cx + sway, 2)
        cr.curve_to(cx + sway + direction * 6, -0.5,
                    cx + sway + direction * 6, 5, cx + sway + direction * 3, 7)
        cr.close_path()
        cr.fill()
    # Orange ball with dark seams stays legible at native overlay size.
    cr.set_source_rgb(1, 0.58, 0.19)
    cr.arc(ball_x, ball_y, 3.5, 0, math.tau)
    cr.fill()
    line([(ball_x - 3, ball_y), (ball_x + 3, ball_y)], dark, 0.65)
    line([(ball_x, ball_y - 3), (ball_x, ball_y + 3)], dark, 0.65)
