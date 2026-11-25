from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, sys.argv[1])
from render_animation_previews import ROW_DURATIONS, save_preview

run = Path(sys.argv[2])
output = run / 'previews'
output.mkdir(exist_ok=True)
frame_root = run / 'qa' / 'encoded-frames'
font = ImageFont.load_default(size=14)
background = (8, 13, 32, 255)

with Image.open(run / 'final' / 'spritesheet-extended.png') as source:
    atlas = source.convert('RGBA')


def get_cell(row, column):
    return atlas.crop((192 * column, 208 * row, 192 * (column + 1), 208 * (row + 1)))


def staged_pose(pose, label):
    card = Image.new('RGBA', (192, 232), background)
    card.alpha_composite(pose)
    ImageDraw.Draw(card).text((96, 219), label, font=font, fill='#DCE4F7', anchor='mm')
    return card.convert('RGB')


states = {}
all_poses = []
all_durations = []
for row, (state, durations) in enumerate(ROW_DURATIONS.items()):
    poses = [get_cell(row, column) for column in range(len(durations))]
    states[state] = poses
    state_dir = frame_root / state
    state_dir.mkdir(parents=True, exist_ok=True)
    for column, pose in enumerate(poses):
        pose.save(state_dir / f'{column:02}.png')
    label = {'running': 'Working', 'running-left': 'Running left', 'running-right': 'Running right'}.get(state, state.capitalize())
    all_poses.extend(staged_pose(pose, label) for pose in poses)
    all_durations.extend(durations)

save_preview(all_poses, all_durations, output / 'Nazar-motion.gif')
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ignore_loop', '1', '-i', str(output / 'Nazar-motion.gif'), '-movflags', '+faststart', '-pix_fmt', 'yuv420p', str(output / 'Nazar-motion.mp4')], check=True)

idle, jump = states['idle'], states['jumping']
jump_loop = [idle[0], *jump, idle[-1]]
jump_times = [300, 120, 130, 140, 130, 120, 350]
save_preview(jump_loop, jump_times, output / 'Nazar-idle-jump-idle.gif')
look = [get_cell(row, column) for row in (9, 10) for column in range(8)]
save_preview(look, [115] * 16, output / 'Nazar-look-loop.gif')

samples = [(idle[0], 'Idle'), (states['waving'][2], 'Wave'), (jump[2], 'Jump apex'), (states['review'][2], 'Review')]
still_sheet = Image.new('RGB', (192 * len(samples), 232), background[:3])
for column, (pose, label) in enumerate(samples):
    still_sheet.paste(staged_pose(pose, label), (192 * column, 0))
still_sheet.save(output / 'Nazar-motion-stills.png')
