import json, tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fix_provider_bootstrap as f

import unittest


class ProviderBootstrapTests(unittest.TestCase):
    def test_migration(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            profile=td/'profile.json'
            seed=td/'YunTu.seed'
            seed.write_text('dummy raw subscription',encoding='utf-8')
            profile.write_text(json.dumps({
              'providers':[{'type':'remote','tag':'YunTu','url':'https://example.invalid/sub','http_client':'provider-download','update_interval':'24h'}],
              'http_clients':[{'tag':'provider-download','headers':{'User-Agent':'clash.meta'},'domain_resolver':'dns-bootstrap'}],
              'experimental':{'cache_file':{'enabled':True}},
              'outbounds':[{'type':'selector','tag':'PROXY','outbounds':['REJECT'],'providers':['YunTu']},{'type':'block','tag':'REJECT'}]
            },indent=2),encoding='utf-8')
            f.patch(profile,'YunTu',str(seed),'PROXY')
            d=json.loads(profile.read_text(encoding='utf-8'))
            p=d['providers'][0]
            self.assertTrue(p['initial_path']==str(seed.resolve()))
            self.assertTrue('path' not in p)
            self.assertTrue(p['http_client']=='provider-update-YunTu')
            c=next(x for x in d['http_clients'] if x['tag']=='provider-update-YunTu')
            self.assertTrue(c['detour']=='PROXY')
            self.assertTrue(c['headers']['User-Agent']=='clash.meta')
            self.assertTrue('domain_resolver' not in c)
            self.assertTrue(d['experimental']['cache_file']['enabled'] is True)
            self.assertTrue(profile.with_suffix('.json.bak').exists())


if __name__ == "__main__":
    unittest.main()
