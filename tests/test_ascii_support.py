import unittest

from sl651 import constants as C
from sl651.ascii_codec import build_ascii_report_body
from sl651.down_builder import build_down_body
from sl651.encoder import build_ack, build_down_frame, build_up_frame
from sl651.framer import FrameSplitter
from sl651.parser import parse_frame


class AsciiSupportTests(unittest.TestCase):
    def test_ascii_down_round_trip(self):
        body = build_down_body(
            0x37,
            serial_no=0,
            send_time="2024-01-09 16:01:28",
            encoding=C.WIRE_ASCII,
        )
        frame = build_down_frame(
            "0010100001",
            0x01,
            "A000",
            0x37,
            body,
            end_flag=C.ENQ,
            encoding=C.WIRE_ASCII,
        )

        parsed = parse_frame(frame)
        self.assertEqual(parsed.header.encoding, C.WIRE_ASCII)
        self.assertEqual(parsed.header.direction, "down")
        self.assertEqual(parsed.body.serial_no, 0)
        self.assertEqual(parsed.body.send_time, "2024-01-09 16:01:28")
        self.assertTrue(parsed.crc_ok)
        self.assertEqual(parsed.errors, [])

    def test_ascii_report_round_trip(self):
        body = build_ascii_report_body(
            0x1234,
            "0010100001",
            station_type=0x48,
            elements=[
                (0x20, 3.5, 3, 1),
                (0x39, 12.34, 4, 2),
            ],
            send_time="2024-01-09 16:01:28",
            observe_time="2024-01-09 16:01",
        )
        frame = build_up_frame(
            0x01,
            "0010100001",
            "A000",
            0x32,
            body,
            encoding=C.WIRE_ASCII,
        )

        parsed = parse_frame(frame)
        self.assertEqual(parsed.header.encoding, C.WIRE_ASCII)
        self.assertEqual(parsed.body.serial_no, 0x1234)
        self.assertEqual(parsed.body.remote_addr, "0010100001")
        self.assertEqual(parsed.body.station_type, 0x48)
        self.assertEqual(parsed.body.observe_time, "2024-01-09 16:01")
        self.assertEqual([e.guide_code for e in parsed.body.elements], ["ST", "TT", "PJ", "Z"])
        self.assertEqual(parsed.body.elements[2].value, 3.5)
        self.assertEqual(parsed.body.elements[3].value, 12.34)
        self.assertTrue(parsed.crc_ok)

        fields_by_label = {field.label: field for field in parsed.fields}
        self.assertEqual(fields_by_label["测站编码引导符"].color, "primary")
        self.assertEqual(fields_by_label["观测时间引导符"].color, "success")
        self.assertEqual(fields_by_label["瞬时河道水位/潮位引导符"].color, "info")
        self.assertEqual(fields_by_label["帧起始符"].color, "neutral")
        self.assertEqual(fields_by_label["正文起始符"].color, "neutral")
        self.assertEqual(fields_by_label["结束符"].color, "neutral")

        covered = set()
        for field in parsed.fields:
            covered.update(range(field.start, field.end))
        end_pos = len(frame) - 5
        self.assertEqual(
            [i for i in range(end_pos) if frame[i] != 0x20 and i not in covered],
            [],
        )

    def test_ascii_m3_and_ack_keep_encoding(self):
        body = build_ascii_report_body(
            1,
            "0010100001",
            elements=[(0x20, 1.2, 3, 1)],
            send_time="2024-01-09 16:01:28",
            observe_time="2024-01-09 16:01",
        )
        frame = build_up_frame(
            1,
            "0010100001",
            "A000",
            0x32,
            body,
            encoding=C.WIRE_ASCII,
            packet_total=2,
            packet_seq=1,
        )
        parsed = parse_frame(frame)
        self.assertTrue(parsed.header.m3)
        self.assertEqual(parsed.header.packet_total, 2)
        self.assertEqual(parsed.header.packet_seq, 1)
        self.assertTrue(parsed.crc_ok)

        ack = build_ack(parsed)
        ack_parsed = parse_frame(ack)
        self.assertEqual(ack_parsed.header.encoding, C.WIRE_ASCII)
        self.assertEqual(ack_parsed.header.direction, "down")
        self.assertTrue(ack_parsed.header.m3)
        self.assertEqual(ack_parsed.header.packet_total, 2)
        self.assertEqual(ack_parsed.header.packet_seq, 2)
        self.assertEqual(ack_parsed.body.serial_no, 1)
        self.assertTrue(ack_parsed.crc_ok)

    def test_ascii_integer_value_is_not_treated_as_identifier(self):
        body = build_ascii_report_body(
            1,
            "0010100001",
            elements=[(0x20, 12, 3, 0)],
            send_time="2024-01-09 16:01:28",
            observe_time="2024-01-09 16:01",
        )
        frame = build_up_frame(
            1,
            "0010100001",
            "A000",
            0x32,
            body,
            encoding=C.WIRE_ASCII,
        )
        parsed = parse_frame(frame)
        self.assertEqual(len(parsed.body.elements), 3)
        self.assertEqual(parsed.body.elements[-1].guide_code, "PJ")
        self.assertEqual(parsed.body.elements[-1].value, 12)

    def test_splitter_handles_mixed_frames_and_partial_input(self):
        binary = build_up_frame(
            1,
            "0010100001",
            "A000",
            0x2F,
            bytes.fromhex("0001240109160128"),
        )
        ascii_body = build_down_body(
            0x37,
            serial_no=0,
            send_time="2024-01-09 16:01:28",
            encoding=C.WIRE_ASCII,
        )
        ascii_frame = build_down_frame(
            "0010100001",
            1,
            "A000",
            0x37,
            ascii_body,
            end_flag=C.ENQ,
            encoding=C.WIRE_ASCII,
        )

        splitter = FrameSplitter()
        frames = []
        payload = b"noise" + binary + ascii_frame
        for index in range(0, len(payload), 3):
            frames.extend(splitter.feed(payload[index : index + 3]))

        self.assertEqual(frames, [binary, ascii_frame])
        self.assertEqual(parse_frame(frames[0]).header.encoding, C.WIRE_HEX_BCD)
        self.assertEqual(parse_frame(frames[1]).header.encoding, C.WIRE_ASCII)

    def test_ascii_config_body_uses_hex_parameter_identifiers(self):
        body = build_down_body(
            0x41,
            serial_no=0,
            send_time="2024-01-09 16:01:28",
            guides=[0x01, 0x03],
            encoding=C.WIRE_ASCII,
        )
        self.assertTrue(body.endswith(b"01 03 "))


if __name__ == "__main__":
    unittest.main()
