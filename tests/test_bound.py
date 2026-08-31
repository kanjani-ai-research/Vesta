from vesta.bound import conclude

C = ("valid", "invalid")

def test_dominant_commit_stands():
    v, oor = conclude({"valid": 0.8, "invalid": 0.2, "indeterminate": 0.3}, C, "indeterminate")
    assert v == "valid" and not oor

def test_near_tie_concludes_undecided():
    v, _ = conclude({"valid": 0.65, "invalid": 0.60, "indeterminate": 0.3}, C, "indeterminate")
    assert v == "indeterminate"

def test_near_tie_with_undecided_also_abstains():
    v, _ = conclude({"valid": 0.66, "invalid": 0.2, "indeterminate": 0.60}, C, "indeterminate")
    assert v == "indeterminate"

def test_undecided_winner_needs_no_margin():
    v, _ = conclude({"valid": 0.5, "invalid": 0.45, "indeterminate": 0.55}, C, "indeterminate")
    assert v == "indeterminate"

def test_region_never_flips_the_winner():
    v, oor = conclude({"valid": 0.2, "invalid": 0.8, "indeterminate": 0.3}, C,
                      "indeterminate", region={"valid", "indeterminate"})
    assert v == "invalid" and oor  # the evidence's winner stands; defiance recorded
