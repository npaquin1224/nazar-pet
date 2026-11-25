from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, sys.argv[1])
from render_animation_previews import ROW_DURATIONS

run = Path(sys.argv[2])
output = run / 'previews'
output.mkdir(exist_ok=True)
frame_root = run / 'qa' / 'encoded-frames'
font = ImageFont.load_default(size=14)
dark_bg = (8, 13, 32, 255)
light_bg = (244, 247, 252, 255)

atlas_candidate = run / 'final' / 'spritesheet-extended.png'
if not atlas_candidate.is_file():
    atlas_candidate = run / 'spritesheet-extended.png'

with Image.open(atlas_candidate) as source:
    atlas = source.convert('RGBA')


def get_cell(row, column):
    return atlas.crop((192 * column, 208 * row, 192 * (column + 1), 208 * (row + 1)))


def staged_pose(pose, label, bg=dark_bg, fg='#DCE4F7'):
    card = Image.new('RGBA', (192, 232), bg)
    card.alpha_composite(pose)
    ImageDraw.Draw(card).text((96, 219), label, font=font, fill=fg, anchor='mm')
    return card.convert('RGB')


def save_optimized_gif(frames, durations, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Build shared global adaptive palette from montage of keyframes for zero palette flicker
    sample_count = min(len(frames), 12)
    strip = Image.new('RGB', (frames[0].width * sample_count, frames[0].height))
    for index in range(sample_count):
        frame_index = round(index * (len(frames) - 1) / max(1, sample_count - 1))
        strip.paste(frames[frame_index].convert('RGB'), (index * frames[0].width, 0))
    pal_img = strip.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    quantized = [f.convert('RGB').quantize(palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG) for f in frames]
    quantized[0].save(
        out_path,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )


states = {}
all_poses_dark = []
all_poses_light = []
all_durations = []
for row, (state, durations) in enumerate(ROW_DURATIONS.items()):
    poses = [get_cell(row, column) for column in range(len(durations))]
    states[state] = poses
    state_dir = frame_root / state
    state_dir.mkdir(parents=True, exist_ok=True)
    for column, pose in enumerate(poses):
        pose.save(state_dir / f'{column:02}.png', optimize=True, compress_level=9)
    label = {'running': 'Working', 'running-left': 'Running left', 'running-right': 'Running right'}.get(state, state.capitalize())
    all_poses_dark.extend(staged_pose(pose, label, dark_bg, '#DCE4F7') for pose in poses)
    all_poses_light.extend(staged_pose(pose, label, light_bg, '#182238') for pose in poses)
    all_durations.extend(durations)

save_optimized_gif(all_poses_dark, all_durations, output / 'Nazar-motion.gif')
save_optimized_gif(all_poses_light, all_durations, output / 'Nazar-motion-light.gif')

# Lossless animated WebP with full 8-bit alpha channel
all_rgba = [pose for state in ROW_DURATIONS for pose in states[state]]
all_rgba[0].save(
    output / 'Nazar-motion.webp',
    save_all=True,
    append_images=all_rgba[1:],
    duration=all_durations,
    loop=0,
    lossless=True,
    quality=90,
)

if shutil.which('ffmpeg'):
    subprocess.run(
        [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-ignore_loop', '1', '-i', str(output / 'Nazar-motion.gif'),
            '-movflags', '+faststart', '-pix_fmt', 'yuv420p',
            str(output / 'Nazar-motion.mp4'),
        ],
        check=True,
    )

idle, jump = states['idle'], states['jumping']
jump_loop = [staged_pose(p, 'Jump', dark_bg, '#DCE4F7') for p in [idle[0], *jump, idle[-1]]]
jump_times = [300, 120, 130, 140, 130, 120, 350]
save_optimized_gif(jump_loop, jump_times, output / 'Nazar-idle-jump-idle.gif')

look = [staged_pose(get_cell(row, column), 'Look', dark_bg, '#DCE4F7') for row in (9, 10) for column in range(8)]
save_optimized_gif(look, [115] * 16, output / 'Nazar-look-loop.gif')

samples = [(idle[0], 'Idle'), (states['waving'][2], 'Wave'), (jump[2], 'Jump apex'), (states['review'][2], 'Review')]
still_sheet = Image.new('RGB', (192 * len(samples), 232), dark_bg[:3])
for column, (pose, label) in enumerate(samples):
    still_sheet.paste(staged_pose(pose, label), (192 * column, 0))
still_sheet.save(output / 'Nazar-motion-stills.png', optimize=True)
still_sheet.resize((still_sheet.width * 2, still_sheet.height * 2), Image.Resampling.NEAREST).save(
    output / 'Nazar-showcase-2x.png', optimize=True
)
