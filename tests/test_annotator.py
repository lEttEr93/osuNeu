import io
import threading
import unittest
import zipfile
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from osuneu.annotator import Handler, load_upload, parse_preview


MAP = b'''osu file format v14
[General]
AudioFilename: song.mp3
Mode: 0
[Metadata]
Title: Test
Artist: Example
Version: Hard
[Difficulty]
SliderMultiplier: 1.4
OverallDifficulty: 7
[TimingPoints]
0,500,4,2,0,100,1,0
1000,-50,4,2,0,100,0,0
3000,600,4,2,0,100,1,0
[HitObjects]
64,64,500,1,0,0:0:0:0:
128,128,1500,2,0,B|200:100|300:200,2,280
256,192,4000,8,0,5000
'''


class AnnotationParserTests(unittest.TestCase):
    def test_slider_velocity_repeats_and_ar_fallback(self):
        bm = parse_preview(MAP, 'test.osu')
        slider = bm['objects'][1]
        self.assertEqual(slider['end'], 2500)
        self.assertEqual(slider['points'][-1], [300, 200])
        self.assertEqual(bm['settings']['ApproachRate'], 7)
        self.assertEqual(bm['bpm'], 120)
        self.assertEqual(bm['objects'][2]['end'], 5000)

    def test_archive_relative_audio_and_nonstandard_filter(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr('folder/test.osu', MAP)
            z.writestr('folder/SONG.MP3', b'audio')
            z.writestr('mania.osu', MAP.replace(b'Mode: 0', b'Mode: 3'))
        maps, assets = load_upload(stream.getvalue(), 'set.osz')
        self.assertEqual(len(maps), 1)
        self.assertEqual(list(assets.values()), [b'audio'])
        self.assertTrue(maps[0]['audioUrl'].startswith('/asset/'))

    def test_identity_and_rejection(self):
        self.assertEqual(parse_preview(MAP, 'a.osu')['id'], parse_preview(MAP, 'b.osu')['id'])
        with self.assertRaises(ValueError):
            parse_preview(MAP.replace(b'Mode: 0', b'Mode: 3'), 'test.osu')
        with self.assertRaises(ValueError):
            parse_preview(b'not a beatmap', 'test.osu')

    def test_red_timing_point_resets_sv(self):
        data = MAP.replace(b'128,128,1500', b'128,128,3500')
        bm = parse_preview(data, 'test.osu')
        self.assertAlmostEqual(bm['objects'][1]['end'], 5900)


class MediaServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.assets = {'test.wav': b'0123456789'}
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, range_header):
        connection = HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request('GET', '/asset/test.wav', headers={'Range': range_header})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_audio_seek_range(self):
        status, headers, data = self.request('bytes=3-6')
        self.assertEqual(status, 206)
        self.assertEqual(headers['Content-Range'], 'bytes 3-6/10')
        self.assertEqual(data, b'3456')

    def test_suffix_and_invalid_ranges(self):
        self.assertEqual(self.request('bytes=-3')[2], b'789')
        self.assertEqual(self.request('bytes=100-')[0], 416)
        self.assertEqual(self.request('bytes=0-1,3-4')[0], 416)


if __name__ == '__main__':
    unittest.main()
