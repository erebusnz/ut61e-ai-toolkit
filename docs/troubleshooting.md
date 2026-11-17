# Connection troubleshooting

1. Run `ut61e devices`. An empty list means no supported USB bridge was
   enumerated; it is not a meter reading. Check the cable and USB connection.
   Supported IDs are CP2110 `10c4:ea80` and CH9329 `1a86:e429`. A WCH cable may
   appear as `WCH UART TO KB-MS_V1.7`; `info` still checks the actual meter name.
2. Run `ut61e info`. A bridge without a responding meter can enumerate but time
   out here. Turn the meter on, align the optical adapter, and enable USB
   communication according to the meter manual. Close UNI-T and other DMM apps.
3. Select `--serial` or `--path-hex` when more than one candidate is listed.
   Default CP2110 serial numbers can be identical, so a path may be necessary.
4. `hid` import/API errors usually mean a missing `hidapi` install or an
   incompatible Python environment. Use the same interpreter for installation
   and execution. Windows requires no replacement USB driver for this path.
5. On Linux, install the distribution's HIDAPI library if the wheel needs it.
   Access to `/dev/hidraw*` may require a udev rule. A locally reviewed rule for
   desktop-session access is:

   ```udev
   SUBSYSTEM=="hidraw", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea80", TAG+="uaccess"
   SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="e429", TAG+="uaccess"
   ```

   This grants access to all bridges with these IDs, not only this DMM. Have
   the system administrator install an appropriate rule and reconnect the
   device. Avoid running the agent or MCP server as root.
6. A bad checksum, malformed display, unknown mode/range, low battery, or
   invalid verdict should be investigated using `raw_hex` and the actual LCD.
   The toolkit does not silently retry a timed-out request or substitute data.

## Hardware validation

See the [2026-11-18 report](hardware-validation-2026-11-18.md) for the completed
Windows/CH9329 acquisition checks. The checklist below also covers physical
measurement comparisons that have not yet been performed.

Use a known, low-voltage source for the initial bench validation:

- Confirm `info` returns UT61E+ and the intended bridge identity.
- Compare positive and negative DC voltage readings with the LCD.
- Verify DCmV converts to V and a known resistor in a k-ohm range converts to ohm.
- With an unpowered setup, verify open resistance leads produce overload and
  shorted leads in continuity mode produce an appropriate numeric reading.
- Enable HOLD/REL on the meter and confirm a check becomes invalid. Restore
  normal measurement manually afterward.
- Capture JSONL, unplug the cable, replay the capture, and verify it remains
  labeled replay. Confirm live reading with a missing device reports an error.

Automated tests use a fake HID device and cannot replace these bench checks.
The toolkit deliberately exposes no remote button commands, range changes,
power control, or arbitrary UART writes.

