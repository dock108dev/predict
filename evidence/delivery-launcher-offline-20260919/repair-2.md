# Bounded repair 2

The replacement suite stopped at the first process test (15 checks reached). Spawned worker/watchdog processes inherit the focused runner's 180-second hard CPU cap; asking for the production 600-second ceiling attempted to raise that inherited hard limit and was rejected. Apply the minimum of the configured ceiling and existing soft/hard CPU limits in both children. This tightens or preserves limits and does not increase the focused or production budget. Retain launcher-2.log; rerun affected launcher checks after this implementation repair.
