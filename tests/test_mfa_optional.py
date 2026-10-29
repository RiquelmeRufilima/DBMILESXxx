from types import SimpleNamespace
from app.services import mfa


def test_totp_encrypted_roundtrip_and_replay_prevention():
    user = SimpleNamespace(preference=SimpleNamespace(settings_json='{}'))
    secret = mfa.generate()
    assert secret not in mfa.encrypt(secret)
    state = mfa.data(user)
    state['mfa_pending_encrypted'] = mfa.encrypt(secret)
    mfa.save(user, state)
    assert mfa.pending_secret(user) == secret
    assert mfa.verify(user, mfa.code(secret))
    assert mfa.verify(user, mfa.code(secret), consume=True)
    assert not mfa.verify(user, mfa.code(secret), consume=True)


def test_single_use_recovery_codes():
    user = SimpleNamespace(preference=SimpleNamespace(settings_json='{}'))
    plain, hashes = mfa.recovery_codes()
    state = mfa.data(user)
    state['mfa_recovery_hashes'] = hashes
    mfa.save(user, state)
    assert mfa.verify_recovery(user, plain[0])
    assert not mfa.verify_recovery(user, plain[0])
    assert len(mfa.data(user)['mfa_recovery_hashes']) == 7
