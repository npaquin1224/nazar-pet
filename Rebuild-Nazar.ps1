param(
    [Parameter(Mandatory)]
    [string]$OutputDir,

    [string]$DirectionSemantics = (Join-Path $PSScriptRoot 'qa/direction-semantics.json')
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$source = $PSScriptRoot
$bundle = Join-Path $source 'pipeline'
$tools = Join-Path $bundle 'skills/create-pet/scripts'
$qa = Join-Path $source 'qa'
$decoded = Join-Path $source 'decoded'
$out = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $out) {
    throw 'Choose a new output directory so the previous revision is preserved.'
}
New-Item -ItemType Directory -Path $out | Out-Null
$frames = Join-Path $out 'frames'
$contactSheet = Join-Path $out 'Nazar-contact-sheet.png'
$directionSheet = Join-Path $out 'Nazar-direction-sheet.png'
$standardAtlas = Join-Path $out 'standard-atlas.png'
$rawAtlas = Join-Path $out 'atlas-before-despill.png'
$registeredRow = Join-Path $out 'look-row-9-registered.png'
$registration = Join-Path $out 'look-row-9-registration.json'
$atlas = Join-Path $out 'spritesheet-extended.png'
$chroma = '#FF00FF'

python (Join-Path $tools 'extract_strip_frames.py') --decoded-dir $decoded --output-dir $frames --method auto | Set-Content (Join-Path $out 'extraction.json')
python (Join-Path $bundle 'register_standard_frames.py') $frames
python (Join-Path $tools 'inspect_frames.py') --frames-root $frames --json-out (Join-Path $out 'frame-review.json') --require-components | Out-Null
python (Join-Path $tools 'compose_atlas.py') --frames-root $frames --output $standardAtlas
python (Join-Path $tools 'assemble_extended_atlas.py') --base-atlas $standardAtlas --look-row-9 (Join-Path $decoded 'look-row-9.png') --registered-row-output $registeredRow --registration-manifest-output $registration --chroma-key $chroma
python (Join-Path $tools 'assemble_extended_atlas.py') --base-atlas $standardAtlas --registered-row-9 $registeredRow --row-9-registration $registration --look-row-10 (Join-Path $decoded 'look-row-10.png') --output $rawAtlas --manifest-output (Join-Path $out 'atlas-registration.json') --chroma-key $chroma
python (Join-Path $tools 'despill_chroma_edges.py') $rawAtlas --output $atlas --json-out (Join-Path $out 'despill.json') --chroma-key $chroma --edge-radius 9 --spill-tolerance 0.25 | Out-Null
python (Join-Path $tools 'validate_atlas.py') $atlas --require-v2 --chroma-key $chroma --json-out (Join-Path $out 'atlas-validation.json') | Out-Null
python (Join-Path $tools 'make_contact_sheet.py') $atlas --output $contactSheet --scale 0.65
python (Join-Path $tools 'make_direction_qa_sheet.py') $atlas --output $directionSheet
python (Join-Path $tools 'measure_direction_continuity.py') $atlas --json-out (Join-Path $out 'look-continuity.json') | Out-Null
python (Join-Path $qa 'render-final-preview.py') $tools $out
python (Join-Path $tools 'render_animation_previews.py') --frames-root (Join-Path $out 'qa/encoded-frames') --output-dir (Join-Path $out 'previews/states') | Out-Null
python (Join-Path $tools 'validate_pet_quality.py') $atlas --atlas-validation (Join-Path $out 'atlas-validation.json') --chroma-report (Join-Path $out 'despill.json') --frame-review (Join-Path $out 'frame-review.json') --require-reviewed-look --direction-semantics $DirectionSemantics --continuity (Join-Path $out 'look-continuity.json') --json-out (Join-Path $out 'validation-extended.json') | Out-Null
Get-FileHash -LiteralPath $atlas -Algorithm SHA256
