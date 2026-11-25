"""Seed a throwaway database for browser tests (fixture data, never shipped)."""
import sys, hashlib
app = sys.argv[1]; data = sys.argv[2]
sys.path.insert(0, app); sys.path.insert(0, app + '/tests')
import httpx
from webapp import core as C, research as R
from pilot.youtube import YouTubeClient
from test_pipeline import fake_api
c = C.connect(data + '/research.db'); cfg = C.config(c)
cfg['seeds'] = {'videos': [], 'handles': [], 'channel_ids': ['UC_one']}
cfg['permissions'].update(ethics=True, collection=True, analysis=True, export=True)
cfg['thresholds'].update(reliability_n=1, min_pairs=1)
C.put(c, 'config', cfg)
client = YouTubeClient('test-key', transport=httpx.MockTransport(fake_api([])), sleep=lambda _: None)
C.expand(c, cfg, client, lambda: None, lambda _: None)
for i in range(130):                                   # enough leads to exercise "Load more"
    C.register(c, f'L{i:010d}', 'manual', 'browser fixture')
for vid in ('AAAAAAAAAA1', 'AAAAAAAAAA5'):
    c.execute("UPDATE inventory SET screening='eligible' WHERE video_id=?", (vid,))
for name in ('coderA', 'coderB'):
    c.execute('INSERT INTO coders VALUES(?,?)', (name, hashlib.sha256(f'token-{name}'.encode()).hexdigest()))
c.commit()
R.create_round(c, cfg, 'Round 1', ['coderA', 'coderB'], 2, 1)
print('seeded')
