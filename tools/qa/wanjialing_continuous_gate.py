"""Reuse the repository's isolated offline gate and preserve earlier attempts."""
import verify_all

verify_all.OUTPUT=verify_all.ROOT/'.cache/qa/wjl22-continuous-2026-11-02/final-offline-gate'
if verify_all.OUTPUT.exists():raise SystemExit('Preserve previous canonical gate evidence')
raise SystemExit(verify_all.main())
