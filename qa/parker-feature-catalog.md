# Parker ideas for Nazar

This catalog collects ideas from the Parker desktop pet for consideration in Nazar. It is a focused source review and a set of proposals. The host's interaction events, state storage, and control over animation transitions have not been verified.

Nazar's current artwork has nine activity states and sixteen look directions. Its failure recoil shipped in PR #7, and its expectant waiting animation shipped in [PR #10](https://github.com/npaquin1224/nazar-pet/pull/10). See [the motion notes](animation-behavior-proposal.md).

## Recommended order

1. Explore curious and focused expressions, a personal greeting, and an idle rhythm using Nazar's eye, lid, and shell.
2. Review transitions, gait, and celebration in motion against the current artwork.
3. Check which interaction events and persistent state the host actually exposes.
4. If supported, prototype one direct interaction and one remembered preference before expanding to needs or goals.

## Animation ideas within existing states

| Idea | Parker inspiration | Nazar experiment | Review |
| --- | --- | --- | --- |
| Expectant waiting | A small response makes reluctance visible | Lift the eye, hold, then settle | Shipped in PR #10 |
| Curious glance | Watching and attention | Brief eye shift with a slight tilt | Read clearly at pet size |
| Concentration | State-driven eyes and posture | Partly lowered lid and deliberate gaze in working or review | Keep work and review distinct |
| Surprise and recovery | Startle followed by slower recovery | Existing failed recoil is shipped | Judge in normal use |
| Relief | Expressions fade at different rates | Relax the lid and settle after a reaction | Check transition to idle |
| Signature greeting | Care reactions include a hop | Small anticipation, clear wave, relaxed return | Check loop and identity |
| Lively idle | Subtle motion while at rest | Gentle breathing, slow blink, small sway | Avoid distracting repeated movement |
| Celebration | Play produces a larger hop | Compare an expressive eye pose with the current jump | Preserve size and landing baseline |
| Inspection | Watching and subtle eye changes | Lean and scan deliberately in review | Distinguish from waiting |
| Focused work | Different intent tempos | A steady rhythm and small controlled eye movement | Read as work rather than movement |
| Characteristic gait | Name-derived bounce, sway, tempo and stride | Give movement a consistent spring and tilt | Check both directions and identity |
| Hesitation | Competing possibilities before a decision | Look between directions, then settle | Keep the meaning readable |
| Gentle drowsiness | Half-lidded eyes and reduced motion | Slower blink and small body settle within an appropriate existing state | Confirm state semantics |
| Consistent mood palette | Mood tints preserve underlying identity | Test subtle changes to existing cyan and violet lighting | Preserve Nazar's recognizable appearance |
| State transitions | Parker eases body changes | Review idle/wave, idle/jump, failure/idle and work/review | Determine which transitions the host controls |

The remaining art ideas are proposals. The fixed sprite contract and host playback determine what can actually be displayed. New artwork needs motion review and validation through the existing pipeline.

## Direct interactions to investigate

| Idea | Parker behavior | Nazar possibility | Needed capability |
| --- | --- | --- | --- |
| Petting | Happiness, hop, heart reaction | Close the eye, lean into touch, settle | Pet or touch event and reaction playback |
| Poking | Startle and a temporary grudge after repeated pokes | Blink or recoil, then a sideways look | Click event; temporary memory for escalation |
| Dragging and release | Window follows a drag; a long fling causes dizziness | Look toward travel and wobble on release | Drag and release events, movement data |
| Play | Raises happiness, uses energy, produces a hop | An eager bounce or a simple follow-the-cursor game | Play event; pointer access for a game |
| Feeding | Named meals have repeatable profiles and reactions | Offer named treats and show a pleased response | Input, feeding trigger, playback |
| Sleep and wake | Energy recovers during sleep; actions soften | Closed lid, slow breathing, gradual wake | Sleep state or event and suitable playback |
| Attention | Nearby cursor or touch can prompt action | Brief glance for small events, full attention for touch | Pointer or event information and gaze selection |
| Acknowledged refusal | Too-tired play produces a visible response | Respond visibly when an interaction cannot proceed | A host event representing the condition |
| Quiet mode | The mind can be paused independently of sleep | Reduce autonomous movement or interruptions | Host support for behavior controls |
| Return greeting | State survives time away | A greeting after an absence | Saved timestamp and return event |

## Personality and continuity

| Idea | Parker behavior | Nazar possibility | Needed capability |
| --- | --- | --- | --- |
| Interaction history | Records meals, games, pets and pokes | Remember a few meaningful interactions | Persistent storage and events |
| Preferences | Learned values influence choices | Favor a greeting, treat or game through experience | State, outcomes and behavior selection |
| Temperament | Read from learned behavior | Develop visible tendencies such as curious or playful | Persistent state and alternative behaviors |
| Needs | Hunger, happiness and energy influence behavior | Start with energy or engagement | Time model, state and ways to respond |
| Small goals | Forms and assesses reachable goals | Seek attention, rest or explore an interaction | State, available actions and goal logic |
| Invented vocabulary | Mints words associated with internal states | Develop a small personal vocabulary | Communication channel and persistent state |
| Teach a word | Associates a supplied word with a current feeling | Teach a greeting or a word for a moment | Input, context, communication and storage |
| Expressive delivery | State changes how words are delivered | Vary timing or sound for excitement and sleepiness | Supported text or audio output |
| Journal and milestones | Reflects on changes in saved state | Record first word, favorite activity or other real events | Event history and a place to present it |
| Growth | Body evolves gradually from life and identity | Develop a new mannerism or artwork variant | Persistent history and validated variants |
| First meeting | Hatches from an egg | A one-time eye-opening and look around | One-time event and sequence playback |
| Personality readout | Mind and goal views explain current state | Show energy, preferences, words and goals | State and an accessible interface |
| Settings | Configurable speed, mood and behavior | Controls for animation, sound and memory | Host or companion settings |
| Preserve history | Saves and reloads state | Keep learned preferences through artwork updates | Stable storage and migration |

## Practical notes from Parker

- Reactions have different recovery times. Parker's startle fades faster than his grudge. A fast response with a slower recovery gives an action weight.
- A named meal produces a stable profile. The same name produces the same basic experience across sessions.
- Parker's words are learned associations. Teaching a word and displaying user-supplied text are separate interactions.
- Parker's goals are formed around states his actions can plausibly reach. A goal system needs actions that can satisfy its goals.
- Parker's behavior remains varied through exploration and satiation. A preference system needs a way to avoid repeating the same action endlessly.
- Parker's journal describes differences in saved state. A Nazar journal should likewise draw on events that actually occurred.
- Parker's optional overlapping-body visualization is off by default because it can look like a rendering fault. A brief hesitation is a more legible visual experiment for Nazar.
- Parker's mathematical decision system is a toy running on an ordinary computer. Any future adaptation should describe its behavior accurately.

## Sources and status

The Parker review covered the interaction, expression, food, body, and brain sources and project documentation. The Nazar repository and recent Nazar thread were checked for existing artwork and recoil work. Host events, stored state, sound, and custom behavior selection require verification before planning implementation.
