# Protocol decisions and sources

The implementation targets the UT61E+ and was written for this toolkit. No
upstream source files or vendor binaries are bundled. The referenced projects
retain their respective licenses; this repository does not relicense them.

References consulted:

- [prickle/UT61E-Multimeter](https://github.com/prickle/UT61E-Multimeter): the
  user-supplied older-UT61E reference. Its C# serial configuration is 19200/7O1,
  unlike the E+ bridge, so its decoder is not used here.
- [ljakob/unit_ut61eplus](https://github.com/ljakob/unit_ut61eplus): the main
  user-supplied E+ reference for requests, payload structure, and range units.
  It is GPL-3.0 licensed. Its bundled `from_vendor/funOl_UT61E+.json` provides
  model-specific unit mappings; mappings for other models must not be substituted.
- [Silicon Labs AN434](https://www.silabs.com/documents/public/application-notes/an434-cp2110-4-interface-specification.pdf):
  primary specification for HID report IDs, UART configuration, and RX purge.
- [dmm-tools protocol research](https://github.com/antoinecellerier/dmm-tools/blob/main/docs/research/ut61eplus/reverse-engineered-protocol.md)
  and its [model table](https://github.com/antoinecellerier/dmm-tools/blob/main/crates/dmm-lib/src/protocol/ut61eplus/tables/ut61e_plus.rs):
  independent hardware observations used to cross-check flags and model ranges.
- [cython-hidapi API](https://trezor.github.io/cython-hidapi/api.html) and
  [MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x):
  transport APIs used by the package. The MCP extra deliberately pins `<2`.
- [HIDAPI Windows backend](https://github.com/libusb/hidapi/blob/master/windows/hid.c):
  `hid_write` can return the padded 64-byte report size even for a shorter
  submitted packet. Both the short and full-size success counts are supported.

The CP2110 bridge uses 9600/8N1. Data report IDs 1..63 encode the UART payload length;
padding must be discarded. Configure using feature reports 0x41 (enable) and
0x50 (UART), then 0x43/0x02 (purge **RX**, not both FIFOs). Configuration is
session setup, not a meter mode change.

CH9329 cables use VID/PID `1a86:e429`, already configured for the meter.
Writes are 65 bytes: zero report ID, UART payload length, data, then zero
padding. Read backends can retain or strip the zero report ID. Only the
declared payload length is decoded: the connected cable returned nonzero
trailing bytes that must not be interpreted as UART data. This was verified
on Windows with an actual UT61E+ on 2026-11-18. No CP2110 configuration reports
are sent to this cable. See the upstream
[CH9329 transport research](https://github.com/antoinecellerier/dmm-tools/blob/main/crates/dmm-lib/src/transport/ch9329.rs)
and the local [hardware report](hardware-validation-2026-11-18.md).

Meter frames start `AB CD`; the length counts the following payload and two
checksum bytes. The checksum is the big-endian 16-bit sum of all preceding
bytes. This toolkit sends only GetName (0x5F) and GetMeasurement (0x5E).
GetName can produce an `FF 00` acknowledgement before its name frame.
Each measurement is requested separately; a request timeout ends acquisition.

A reading has 14 payload bytes: mode, ASCII range index, seven ASCII display
characters, two bar-graph bytes, and three flag bytes. The entire frame is 19
bytes. Units come from the mode **and** range. Decimal arithmetic applies
prefixes before comparison. The original display and frame remain in output.

Important interpretation decisions:

- The three flags use a 0x30 high nibble. The auto-range flag is inverted.
- HOLD, MIN/MAX and peak modes can report stored values. REL reports a
  difference. These are ineligible for absolute live checks.
- Flag 3 bit 3 is exposed as `ac_component`; it is not treated as a general DC
  detector. The mode byte determines AC/DC for ordinary measurements. Combined
  AC+DC mode alternates components, so generic checks exclude it.
- DCV/ACV ranges 0..3 use V; the separate DCmV/ACmV modes use mV. Some older
  research prose conflicts with the model-specific tables on this point; the
  E+ vendor unit mapping and the current independently tested table agree.
- An unrecognized range or mode keeps the raw data but yields no numeric value.
  The uncertain A range index zero, hFE, and NCV cannot pass numeric checks.
- Timestamp is host reception time, not an instrument acquisition timestamp.
  Equal consecutive values need not be independent ADC conversions.

The automated suite validates protocol behavior using synthetic and referenced
wire examples and a fake HID device. It does not establish physical accuracy,
electrical safety, or hardware compatibility. Record model, USB ID, raw frames,
and observed display when validating against a real meter.

