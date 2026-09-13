"""Build Image Draw Bot on Windows with PyInstaller.

Usage:
    py -3 build_exe.py            # recommended onedir build
    py -3 build_exe.py --onefile  # optional single-file build
"""
from pathlib import Path
import subprocess
import sys
from Version import APP_VERSION, FILE_VERSION


def main():
    if sys.platform != 'win32':
        raise SystemExit('The Windows EXE build must run on Windows. Use Build-Release.bat or the GitHub Actions workflow.')
    if sys.maxsize <= 2**32:
        raise SystemExit('Use 64-bit Python to build the Windows x64 release.')

    base = Path(__file__).resolve().parent
    version_text=(base/'version_info.txt').read_text(encoding='utf-8')
    if f"FileVersion', '{FILE_VERSION}'" not in version_text or f"ProductVersion', '{FILE_VERSION}'" not in version_text:
        raise SystemExit('Version mismatch: update version_info.txt to match Version.py before building.')
    onefile = '--onefile' in sys.argv[1:]
    gpu_build = '--gpu' in sys.argv[1:]
    builder = base / '.build-venv' / 'Scripts' / 'python.exe'
    if not builder.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(base / '.build-venv')], check=True)

    subprocess.run([str(builder), '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
    subprocess.run([
        str(builder), '-m', 'pip', 'install', '-r', str(base / 'requirements.txt'),
        'pyinstaller>=6.22.2,<7'
    ], check=True)
    # Step 22 is part of the standard Windows build: bundle PyOpenCL so AMD,
    # Intel and NVIDIA OpenCL devices can be benchmarked without modifying the
    # user's Python environment. The vendor driver/ICD is still system-provided.
    subprocess.run([str(builder), '-m', 'pip', 'install', '-r', str(base / 'requirements-gpu-universal.txt')], check=True)
    if gpu_build:
        subprocess.run([str(builder), '-m', 'pip', 'install', '-r', str(base / 'requirements-gpu-nvidia.txt')], check=True)

    mode = '--onefile' if onefile else '--onedir'
    command = [
        str(builder), '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--noupx', '--log-level', 'WARN', mode, '--windowed',
        '--name', 'ImageDrawBot',
        '--icon', str(base / 'assets' / 'image-draw-bot-icon.ico'),
        '--hidden-import', 'AppBranding',
        '--hidden-import', 'GettingStarted',
        '--hidden-import', 'TaskbarIdentity',
        '--add-data', str(base / 'assets' / 'image-draw-bot-icon.png') + ';assets',
        '--add-data', str(base / 'assets' / 'image-draw-bot-icon.ico') + ';assets',
        '--manifest', str(base / 'ImageDrawBot.manifest'),
        '--version-file', str(base / 'version_info.txt'),
        '--hidden-import', 'PIL.ImageGrab',
        '--hidden-import', 'PIL.ImageTk',
        '--hidden-import', 'MouseProbe',
        '--hidden-import', 'TargetProbe',
        '--hidden-import', 'TargetCapture',
        '--hidden-import', 'PaintTools',
        '--hidden-import', 'PaintAutoCalibration',
        '--hidden-import', 'PaintToolCalibration',
        '--hidden-import', 'CalibrationAnchors',
        '--hidden-import', 'RuntimePaths',
        '--hidden-import', 'ReleaseState',
        '--hidden-import', 'UpdateCenter',
        '--hidden-import', 'GpuAcceleration',
        '--hidden-import', 'GpuHardware',
        '--hidden-import', 'AutoGpuSetup',
        '--hidden-import', 'AutoUniversalGpuSetup',
        '--hidden-import', 'UniversalHardwareBenchmark',
        '--hidden-import', 'UniversalGpuAcceleration',
        '--hidden-import', 'CudaPalette',
        '--hidden-import', 'FillOptimizer',
        '--hidden-import', 'RegionFillEngine',
        '--hidden-import', 'DrawTimeEstimate',
        '--hidden-import', 'DrawTimeCalibration',
        '--hidden-import', 'TimeBudgetEngine',
        '--hidden-import', 'VisualImportanceMap',
        '--hidden-import', 'AdaptiveDeadlineRenderer',
        '--hidden-import', 'DeadlineScheduler',
        '--hidden-import', 'AccuracyEvaluator',
        '--hidden-import', 'PreviewDiagnostics',
        '--hidden-import', 'DetailZoomPass',
        '--hidden-import', 'QuickSketchFillContour',
        '--hidden-import', 'HybridRenderer3',
        '--hidden-import', 'Sketch2Planner',
        '--hidden-import', 'SketchFillRenderer',
        '--hidden-import', 'BenchmarkSuite',
        '--hidden-import', 'EndToEndAutoTuner',
        '--hidden-import', 'AutoTunerFeedback',
        '--hidden-import', 'SafeCanvasSnapshotScoring',
        '--hidden-import', 'PostDrawCorrectionPass',
        '--hidden-import', 'CorrectionReviewRecovery',
        '--hidden-import', 'CorrectionHistory',
        '--hidden-import', 'GoldenImageRegression',
        '--hidden-import', 'ReleaseStabilityHardening',
        '--hidden-import', 'ColorGrouping',
        '--hidden-import', 'AdvancedColor',
        '--hidden-import', 'SmartTools',
        '--hidden-import', 'UIState',
        '--hidden-import', 'PreviewLayers',
        '--hidden-import', 'PreviewQuality',
        '--hidden-import', 'ExtraFast',
        '--hidden-import', 'PaintFullCalibration',
        '--hidden-import', 'ProfileIsolation',
        '--hidden-import', 'ProfileStorage',
        '--hidden-import', 'CalibrationState',
        '--hidden-import', 'ColorCache',
        '--add-data', str(base / 'assets' / 'paint-tools-reference.png') + ';assets',
        '--add-data', str(base / 'STEP-13-REAL-RESULT-VERIFICATION.md') + ';.',
        '--add-data', str(base / 'STEP-14-POST-DRAW-CORRECTION-PASS.md') + ';.',
        '--add-data', str(base / 'STEP-15-CORRECTION-REVIEW-RECOVERY-UI.md') + ';.',
        '--add-data', str(base / 'STEP-16-CORRECTION-HISTORY-BEFORE-AFTER.md') + ';.',
        '--add-data', str(base / 'STEP-17-GOLDEN-IMAGE-REGRESSION.md') + ';.',
        '--add-data', str(base / 'STEP-18-RELEASE-STABILITY-HARDENING.md') + ';.',
        '--add-data', str(base / 'STEP-23-UNIVERSAL-GPU-ACCELERATION.md') + ';.',
        '--add-data', str(base / 'STEP-24-ADAPTIVE-DETAIL-ZOOM.md') + ';.',
        '--add-data', str(base / 'STEP-25-QUICK-SKETCH-FILL-CONTOUR.md') + ';.',
        '--add-data', str(base / 'golden-regression') + ';golden-regression',
        '--hidden-import', 'PreviewSafety',
        '--hidden-import', 'ResourceAllocation',
        '--hidden-import', 'ResourceScheduler',
        '--hidden-import', 'PerformanceAutoTuner',
        '--hidden-import', 'StrokeDelivery',
        '--hidden-import', 'StrokeDeliveryVerification',
        '--hidden-import', 'BrowserBrushSize',
        '--hidden-import', 'GarticOpacity',
        '--hidden-import', 'CompletedDrawingAnalysis','DrawingStyleProfiles',
        '--hidden-import', 'BackgroundRemoval',
        '--hidden-import', 'BrowserToolLayout',
        '--hidden-import', 'SkribblFastRenderer',
        '--hidden-import', 'GarticPhoneFastRenderer',
        '--hidden-import', 'GarticPhoneLayout',
        '--hidden-import', 'GarticEngineV2',
        '--hidden-import', 'ProfileEngine',
        '--hidden-import', 'DropInStart',
        '--hidden-import', 'DropInSynchronization',
        '--hidden-import', 'FastDryRun',
        '--hidden-import', 'CanvasGuard',
        '--hidden-import', 'CanvasAnchorDetection',
        '--hidden-import', 'AnchorTransform',
        '--hidden-import', 'EdgeDetection',
        '--hidden-import', 'EdgeBehavior',
        '--hidden-import', 'SafeFillMask',
        '--hidden-import', 'SafetyDebugOverlay',
        '--hidden-import', 'RuntimeSafetyReport',
        '--hidden-import', 'LocalSanitization',
        '--hidden-import', 'PerformanceProfiler',
        '--hidden-import', 'ProgressiveRenderer',
        '--hidden-import', 'PlanningWatchdog',
        '--hidden-import', 'ShapePaths',
        '--hidden-import', 'SessionRecovery',
        '--hidden-import', 'RenderResume',
        '--hidden-import', 'SmartRecovery',
        '--hidden-import', 'VisualVerification',
        '--hidden-import', 'DiagnosticsPackage',
        '--hidden-import', 'ContinuousPaths',
        '--hidden-import', 'StrokeOptimizer',
        '--hidden-import', 'AdaptiveDetail',
        '--hidden-import', 'DetailFidelityPlanner',
        '--hidden-import', 'PixelAccuratePlanner',
        '--hidden-import', 'PicturePalettePlanning',
        '--hidden-import', 'PicturePaletteRefinement',
        '--hidden-import', 'PictureCustomPalette',
        '--hidden-import', 'ShadowDetailEngine',
        '--hidden-import', 'PixelStrokeEngine',
        '--hidden-import', 'HybridCostModel',
        '--hidden-import', 'HybridBenchmark',
        '--hidden-import', 'PixelAccuracyEngine',
        '--hidden-import', 'AdaptiveBrushEngine',
        '--hidden-import', 'PixelAccuracyGpu',
        '--hidden-import', 'AppToolCalibration',
        '--hidden-import', 'AppTools',
        '--hidden-import', 'Version',
        '--hidden-import', 'VersionHistory',
        '--hidden-import', 'MobilePreview',
        '--hidden-import', 'BrowserAutoCalibration',
        '--hidden-import', 'BrowserAutoRecalibration',
        '--hidden-import', 'CalibrationHealth',
        '--hidden-import', 'BrowserVisualPreflight',
        '--hidden-import', 'OneClickSetupVerification',
        '--hidden-import', 'TargetCapabilities',
        '--hidden-import', 'LayoutFingerprintV2',
        '--hidden-import', 'RealSpeedBudget',
        '--hidden-import', 'qrcode',
        '--collect-all', 'tkinterdnd2',
        '--collect-all', 'customtkinter',
        '--collect-all', 'pyopencl',
        '--hidden-import', 'keyboard',
        '--hidden-import', 'ExactColorCalibration',
        '--hidden-import', 'ExactColorTools',
        '--hidden-import', 'DynamicColors',
        '--hidden-import', 'ColorMatchingEngine',
        '--hidden-import', 'CanvasClear',
        '--hidden-import', 'PreviewDetailEngine',
        '--hidden-import', 'AdaptiveColor',
        '--hidden-import', 'AdaptiveColorCount',
        '--hidden-import', 'TimeAwareColorBudget',
        '--hidden-import', 'ColorFidelity',
        '--hidden-import', 'CrashDumpConfig',
        '--hidden-import', 'SubjectFocus',
        '--hidden-import', 'ImageFormatInfo',
        '--hidden-import', 'ImageUpscale',
        '--hidden-import', 'SubjectSelector',
        '--hidden-import', 'SketchPlanner',
        '--hidden-import', 'AutoSketchBudget',
        '--hidden-import', 'GarticTimer',
        '--hidden-import', 'AutoDrawing',
        '--hidden-import', 'GarticSketchPaths',
        '--hidden-import', 'StudioUI',
        '--hidden-import', 'PreviewDeck',
        '--hidden-import', 'WorkspaceLayout',
        '--hidden-import', 'ResponsiveRows',
        '--hidden-import', 'SmoothScroll',
        '--hidden-import', 'ScreenTaskWindow',
        '--hidden-import', 'ProfilePolish',
        '--hidden-import', 'BeginnerSetupWizard',
    ]
    if gpu_build:
        command.extend(['--collect-all', 'cupy', '--collect-all', 'cupyx', '--hidden-import', 'cupyx.scipy.ndimage'])

    # Keep the frozen application clean. Runtime-critical data above remains a
    # hard requirement; historical/help documentation here is optional and may
    # have been intentionally removed from the current release tree.
    optional_data = [
        'Collect-Diagnostics.bat', 'Enable-Crash-Dumps.bat', 'Disable-Crash-Dumps.bat',
        'palette-index-maps.json', 'MOTIVFOKUS.md', 'IMAGE-FORMATS.md', 'UPSCALING.md', 'README.md',
        'STEP-9-CALIBRATION-STATE-PROFILE-ISOLATION.md', 'STEP-10-PREVIEW-DIAGNOSTICS-BENCHMARKS.md',
        'STEP-11-END-TO-END-AUTO-TUNER.md', 'STEP-12-AUTO-TUNER-FEEDBACK-LOOP.md',
        'STEP-16-CORRECTION-HISTORY-BEFORE-AFTER.md', 'STEP-17-GOLDEN-IMAGE-REGRESSION.md',
        'STEP-18-RELEASE-STABILITY-HARDENING.md', 'RELEASE-NOTES-Step19-Step20-Profile-Polish-UX-Wizard.md',
        'STEP-20-BEGINNER-SETUP-WIZARD.md', 'STEP-19-FINAL-PROFILE-POLISH.md',
        'STEP-21-BUILD-PUBLISHER-GITHUB-RELEASE.md', 'RELEASE-NOTES-Step21-Build-Publisher-GitHub-Release.md',
        'GITHUB-RELEASE-TEMPLATE.md', 'ROADMAP-STEP22-PLUS.md', 'golden-regression', 'README-INDEX.md',
        'VERSION-HISTORY.md', 'RELEASE-NOTES-v1.0.90-beta.md', 'RELEASE-NOTES-v1.0.90-Adaptive-Brush.md',
        'RELEASE-NOTES-v1.0.91-beta.md', 'RELEASE-NOTES-v1.0.92-beta.md', 'RELEASE-NOTES-v1.0.93-beta.md',
        'RELEASE-NOTES-v1.0.94-beta.md', 'RELEASE-NOTES-v1.0.103-beta.md', 'RELEASE-NOTES-v1.0.124-beta.md',
        'RELEASE-NOTES-v1.0.123-beta.md', 'RELEASE-NOTES-v1.0.120-beta.md', 'RELEASE-NOTES-v1.0.119-beta.md',
        'RELEASE-NOTES-v1.0.118-beta.md', 'RELEASE-NOTES-v1.0.117-beta.md', 'WORKSPACE-v1.0.92.md',
        'RELEASE-NOTES-v1.0.89-beta.md', 'RELEASE-NOTES-v1.0.88-beta.md', 'RELEASE-NOTES-v1.0.87-beta.md',
        'RELEASE-NOTES-v1.0.86-beta.md', 'RELEASE-NOTES-v1.0.85-rc1.md', 'RELEASE-NOTES-v1.0.83-rc3.md',
        'docs', 'requirements-gpu-nvidia.txt', 'Install-GPU-NVIDIA.bat', 'requirements-gpu-universal.txt',
        'Install-GPU-Universal.bat', 'STEP-22-UNIVERSAL-HARDWARE-AUTO-BENCHMARK.md',
        'RELEASE-NOTES-Step22-Universal-Hardware-Auto-Benchmark.md', 'STEP-24-ADAPTIVE-DETAIL-ZOOM.md',
        'STEP-25-QUICK-SKETCH-FILL-CONTOUR.md', 'STEP-29-HYBRID-RENDERER-3.md',
        'RELEASE-NOTES-Step24-Step25-Detail-Zoom-Quick-Sketch.md', 'COLOR-ENGINE-NAMED-COLOR-INTELLIGENCE.md',
        'RELEASE-NOTES-Step26-Color-Engine-Named-Color-Intelligence.md', 'RELEASE-NOTES-v1.0.131-beta.md'
    ]
    for name in optional_data:
        source = base / name
        if source.exists():
            command.extend(['--add-data', str(source) + ';.'])

    command.append(str(base / 'DrawBot.py'))
    subprocess.run(command, cwd=base, check=True)

    output = base / 'dist' / ('ImageDrawBot.exe' if onefile else 'ImageDrawBot/ImageDrawBot.exe')
    if not output.is_file() or output.read_bytes()[:2] != b'MZ':
        raise SystemExit('The build did not produce a valid Windows EXE.')

    print('\nDone!')
    print(f'EXE: {output}')
    print(f'Built Image Draw Bot {APP_VERSION}.')
    print('Image analysis backend: CUDA bundle included + universal OpenCL benchmark.' if gpu_build else 'Image analysis backend: CPU renderer + universal OpenCL hardware benchmark; optional CUDA available in source mode.')
    print('Manifest: asInvoker (no automatic administrator prompt).')
    print('Run Paint and Image Draw Bot at the same privilege level; normally both without administrator rights.')
    print('The EXE is unsigned, so Windows SmartScreen may show a warning.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'Build failed. Read the error message above. Code: {error.returncode}')
