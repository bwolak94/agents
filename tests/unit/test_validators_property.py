"""
Property-based tests for api.validators using Hypothesis.
Run with: pip install hypothesis && python3 -m pytest tests/unit/test_validators_property.py -v
"""
import pytest

try:
    from hypothesis import given, settings, strategies as st
    _HYPOTHESIS = True
except ImportError:
    _HYPOTHESIS = False
    pytest.skip("hypothesis not installed", allow_module_level=True)

from api.validators import validate_session_id, SESSION_ID_RE


# ── Property: any string matching the regex is accepted ──────────────────────

_VALID_CHARS = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="-_",
    ),
    min_size=1,
    max_size=64,
)


@pytest.mark.asyncio
@given(session_id=_VALID_CHARS)
@settings(max_examples=200)
def test_valid_session_ids_never_raise(session_id: str):
    """Any alphanumeric string (+ dash/underscore, 1-64 chars) must be accepted."""
    if SESSION_ID_RE.fullmatch(session_id):
        # Should not raise
        validate_session_id(session_id)


# ── Property: strings containing forbidden chars always raise ─────────────────

_BAD_CHARS = st.text(
    alphabet=st.characters(whitelist_categories=("P", "S", "Zs")),
    min_size=1,
    max_size=10,
)


@pytest.mark.asyncio
@given(session_id=_BAD_CHARS)
@settings(max_examples=200)
def test_invalid_session_ids_always_raise(session_id: str):
    """Strings with punctuation/symbols that break the regex must raise."""
    if not SESSION_ID_RE.fullmatch(session_id):
        with pytest.raises(Exception):
            validate_session_id(session_id)


# ── Property: empty string always raises ─────────────────────────────────────

def test_empty_session_id_raises():
    with pytest.raises(Exception):
        validate_session_id("")


# ── Property: length > 64 always raises ──────────────────────────────────────

@pytest.mark.asyncio
@given(session_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=65))
@settings(max_examples=50)
def test_too_long_session_id_raises(session_id: str):
    with pytest.raises(Exception):
        validate_session_id(session_id)


# ── Contract: validate_session_id never silently truncates ───────────────────

@pytest.mark.asyncio
@given(
    good=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=64),
    bad_suffix=st.text(alphabet="!@#$%^&*()", min_size=1, max_size=5),
)
@settings(max_examples=100)
def test_contract_no_silent_truncation(good: str, bad_suffix: str):
    """Appending forbidden chars to a valid id must still raise — no silent truncation."""
    combined = good + bad_suffix
    if not SESSION_ID_RE.fullmatch(combined):
        with pytest.raises(Exception):
            validate_session_id(combined)
