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
    """Wave strands briefly resolve into a dribbling figure and a separate ball."""
    if level < 0.001:
        draw_waves(cr, 0, 0, width, height, accent)
        return
    cr.save()
    cr.translate(width / 2, height / 2)
    cr.scale(1, height / 31 * (0.10 + 0.90 * level))
    bounce = (1 - math.cos(phase * 2)) / 2
    lean = math.sin(phase * 2) * 1.5
    shoulder = (-10 + lean, -5 + bounce)
    hip = (-13, 3 + bounce)
    ball = (17 + math.sin(phase) * 2, 10 - bounce * 13)

    # The surrounding threads continue through the figure, so it belongs to
    # the waveform. Silhouettes are only clipping masks, never filled shapes.
    threads = _wave_thread_pattern(cr, phase, width)
    _paint_wave_threads(cr, threads, level, width, accent, 0.07)
    cr.save()
    cr.new_path()
    cr.arc(shoulder[0] + 1, -10 + bounce, 3.2, 0, math.tau)
    _wave_limb(cr, shoulder, hip, 3.3)
    _wave_limb(cr, shoulder, (-21, -1 + bounce), 1.5)
    _wave_limb(cr, (-21, -1 + bounce), (-17, 3 + bounce), 1.3)
    _wave_limb(cr, shoulder, (1, -3 + bounce), 1.5)
    _wave_limb(cr, (1, -3 + bounce), (ball[0] - 2, ball[1] - 5), 1.2)
    _wave_limb(cr, hip, (-22 - lean, 8), 1.9)
    _wave_limb(cr, (-22 - lean, 8), (-19 - lean, 13), 1.6)
    _wave_limb(cr, hip, (-4 + lean, 7), 1.9)
    _wave_limb(cr, (-4 + lean, 7), (2 + lean, 13), 1.6)
    cr.clip()
    _paint_wave_threads(cr, threads, level, width, foreground, 0.78)
    cr.restore()

    cr.save()
    cr.new_path()
    cr.arc(*ball, 4.1, 0, math.tau)
    cr.clip()
    _paint_wave_threads(cr, threads, level, width, (1.0, 0.64, 0.34), 0.85)
    cr.restore()
    cr.restore()
    if level > 0.001:
        draw_ripples(cr, level * (1 - bounce), phase * 2,
                     width / 2 + ball[0], height - 2,
                     width * 0.31, 1.5, accent)


def _wave_limb(cr, start, end, radius):
    """Append a capsule to a clipping path without painting a solid limb."""
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    cr.new_sub_path()
    cr.arc(*start, radius, angle + math.pi / 2, angle + 3 * math.pi / 2)
    cr.arc(*end, radius, angle - math.pi / 2, angle + math.pi / 2)
    cr.close_path()


def _wave_thread_pattern(cr, phase, width):
    """Rasterize once before applying the expensive silhouette clips."""
    cr.push_group_with_content(cairo.CONTENT_ALPHA)
    cr.set_source_rgba(1, 1, 1, 1)
    cr.set_line_width(0.65)
    cr.new_path()
    for row in range(19):
        baseline = -15 + row * 1.65
        for i in range(93):
            x = (i / 92 - 0.5) * (width - 24)
            y = baseline + 0.65 * math.sin(x * 0.28 - phase * 2 + row * 0.65)
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
    cr.stroke()
    return cr.pop_group()


def _paint_wave_threads(cr, threads, level, width, color, opacity):
    gradient = cairo.LinearGradient(-width / 2, 0, width / 2, 0)
    alpha = opacity * (0.25 + 0.75 * level)
    for position, strength in ((0, 0), (0.3, 0.12), (0.43, 1), (0.57, 1), (0.7, 0.12), (1, 0)):
        gradient.add_color_stop_rgba(position, *color, alpha * strength)
    cr.set_source(gradient)
    cr.mask(threads)
