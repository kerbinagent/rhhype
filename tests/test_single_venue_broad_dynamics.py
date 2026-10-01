import unittest
from scripts.single_venue_broad_dynamics import summarize


class DynamicsTests(unittest.TestCase):
    def test_exact_forward_match_and_missing_tail(self):
        rows=[dict(t=t*10**9,second=t,rh_mid='100',core_mid=p,basis_bps=b)
              for t,p,b in [(3,'101','100'),(13,'100.5','50'),(63,'101.5','150')]]
        s=summarize(rows)
        self.assertEqual(s['horizons'][0]['matched'],1)
        self.assertEqual(s['horizons'][0]['missing'],2)
        self.assertEqual(s['horizons'][0]['basis_change_bps']['mean'],'-50')
        self.assertEqual(s['horizons'][1]['matched'],1)
        self.assertEqual(s['horizons'][1]['basis_change_bps']['mean'],'50')

    def test_prior_or_too_late_samples_do_not_match(self):
        rows=[dict(t=int(t*10**9),second=int(t),rh_mid='100',core_mid='101',basis_bps='100')
              for t in (3,12.9,14.1)]
        self.assertEqual(summarize(rows)['horizons'][0]['matched'],0)


if __name__=='__main__':unittest.main()
