"""Verification policy for source claims."""
def verify_claim(claim: dict, *, methodology_available: bool, source_quality: float) -> dict:
    verified = methodology_available and source_quality >= 0.7
    return {**claim, "status": "verified" if verified else "candidate", "verification_reason": "methodology_and_quality_review" if verified else "original methodology unavailable or source quality is low"}
