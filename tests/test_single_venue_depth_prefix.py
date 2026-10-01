import unittest
from pathlib import Path
from scripts import single_venue_depth_prefix as prefix
from scripts import single_venue_depth as original

class PrefixTests(unittest.TestCase):
    def test_original_completed_capture_gate_still_rejects(self):
        prefix.replication.configure()
        with self.assertRaises(AssertionError):
            original.multi_inputs({},original.NAMES['LIT'],prefix.MANIFEST)

    def test_prefix_is_exactly_bound_and_keeps_engine(self):
        prefix.replication.configure()
        with self.assertRaises(AssertionError):prefix.inputs({},prefix.NAME,'0'*64)
        self.assertIs(prefix.study.Study,original.Study)

    def test_auditor_only_changes_coverage_gate_and_labels(self):
        root=Path(__file__).resolve().parents[1]
        expected=(root/'scripts/audit_single_venue_study.py').read_text()
        expected=expected.replace("    assert not result['error'] and result['complete_capture_verified']",
            "    assert not result['error'] and result['observed_prefix_verified']\n"
            "    assert result['complete_capture_verified'] is False and result['retrospective'] is True\n"
            "    assert result['end']['truncated'] and result['end']['reason']=='compressed_size_cap'")
        expected=expected.replace('raw_capture_verified=True,',
            'raw_capture_verified=True, complete_capture_verified=False, descriptive_incomplete_prefix=True,')
        self.assertEqual(expected,(root/'scripts/audit_single_venue_depth_prefix.py').read_text())

if __name__=='__main__':unittest.main()
